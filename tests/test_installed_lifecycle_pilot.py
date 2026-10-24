"""Offline state-machine tests for the tunaOS#3798 installed lifecycle pilot.

The runtime gate is intentionally not exercised here: these tests use a fake
backend and prove ordering, fail-closed state, timeout handling, deployment
mismatch handling, skipped-stage reporting, and cleanup precedence without
opening a disk or touching the host root.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/installed-lifecycle-pilot.py"
SCHEMA = json.loads(
    (ROOT / "schemas/installed-lifecycle-evidence-v1.schema.json").read_text()
)
SPEC = importlib.util.spec_from_file_location("installed_lifecycle_pilot", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

A = "ghcr.io/tuna-os/skipjack@sha256:" + "a" * 64
B = "ghcr.io/tuna-os/skipjack@sha256:" + "b" * 64
HEAD = "1" * 40
HARNESS = "2" * 40


def config(tmp_path: Path, **overrides):
    values = {
        "disk": tmp_path / "installed-a.qcow2",
        "disk_sha256": "3" * 64,
        "image_a": A,
        "image_b": B,
        "ssh_key": tmp_path / "id_ed25519",
        "ssh_user": "root",
        "ssh_port": 2222,
        "output_dir": tmp_path / "evidence",
        "source_run_id": "40025622951/1",
        "source_head_sha": HEAD,
        "harness_sha": HARNESS,
        "confirmed": True,
    }
    values.update(overrides)
    return MODULE.PilotConfig(**values)


class FakeBackend:
    failure_at = None
    failure_category = "timeout"
    cleanup_failure = False
    instances = []

    def __init__(self, pilot_config, command_events):
        self.config = pilot_config
        self.calls = []
        self.verify_count = 0
        type(self).instances.append(self)

    def _call(self, name, result=None):
        self.calls.append(name)
        if self.failure_at == name:
            raise MODULE.PilotFailure(self.failure_category, f"{name} failed")
        return result or {"operation": name}

    def preflight(self):
        return self._call("preflight", {"images": {"a": A, "b": B}})

    def prepare_disk(self):
        return self._call("prepare_disk")

    def start_vm(self):
        self._call("start_vm")

    def wait_for_ssh(self, _timeout):
        self._call("wait_for_ssh")

    def verify_boot(self, expected):
        self.verify_count += 1
        name = f"verify_boot_{self.verify_count}"
        self._call(name)
        return {"reference": expected, "desktop_contract": {"outcome": "passed"}}

    def stage_update(self):
        return self._call("stage_update")

    def reboot(self):
        self._call("reboot")

    def stage_rollback(self):
        return self._call("stage_rollback")

    def cleanup(self):
        self.calls.append("cleanup")
        if self.cleanup_failure:
            raise MODULE.PilotFailure("cleanup_failed", "cleanup also failed")
        return {"removed": ["disposable.qcow2"]}


@pytest.fixture(autouse=True)
def reset_fake_backend():
    FakeBackend.failure_at = None
    FakeBackend.failure_category = "timeout"
    FakeBackend.cleanup_failure = False
    FakeBackend.instances = []


def stage_map(evidence):
    return {stage["id"]: stage for stage in evidence["stages"]}


def test_success_is_exact_a_to_b_to_a_and_schema_validates(tmp_path):
    evidence, passed = MODULE.execute_pilot(config(tmp_path), FakeBackend)

    assert passed
    backend = FakeBackend.instances[-1]
    assert backend.calls == [
        "preflight",
        "prepare_disk",
        "start_vm",
        "wait_for_ssh",
        "verify_boot_1",
        "stage_update",
        "reboot",
        "verify_boot_2",
        "stage_rollback",
        "reboot",
        "verify_boot_3",
        "cleanup",
    ]
    assert evidence["outcomes"] == {
        "cold": "passed",
        "warm": "passed",
        "recovery": "passed",
    }
    assert evidence["result"] == {
        "verdict": "passed",
        "runtime_acceptance": "passed",
        "first_failure": None,
    }
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(evidence)


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"image_b": A}, "identical_images"),
        ({"image_a": "ghcr.io/tuna-os/skipjack:gnome"}, "missing_identity"),
        ({"platform": "linux/arm64"}, "wrong_target"),
        ({"confirmed": False}, "safety_confirmation_missing"),
    ],
)
def test_invalid_identity_is_rejected_before_disk_preparation(tmp_path, overrides, category):
    evidence, passed = MODULE.execute_pilot(config(tmp_path, **overrides), FakeBackend)

    assert not passed
    backend = FakeBackend.instances[-1]
    assert backend.calls == ["cleanup"]
    assert evidence["result"]["first_failure"]["category"] == category
    stages = stage_map(evidence)
    assert stages["preflight"]["outcome"] == "failed"
    assert stages["prepare_disk"]["outcome"] == "skipped"
    assert stages["cleanup"]["outcome"] == "passed"


def test_timeout_skips_all_dependent_stages_but_still_cleans_up(tmp_path):
    FakeBackend.failure_at = "stage_update"
    evidence, passed = MODULE.execute_pilot(config(tmp_path), FakeBackend)

    assert not passed
    stages = stage_map(evidence)
    assert stages["stage_update_b"]["outcome"] == "failed"
    for stage_id in ("warm_boot_b", "stage_rollback_a", "recovery_boot_a"):
        assert stages[stage_id] == {
            "id": stage_id,
            "required": True,
            "outcome": "skipped",
            "details": {"reason": "blocked_by:stage_update_b"},
        }
    assert stages["cleanup"]["outcome"] == "passed"
    assert evidence["result"]["first_failure"] == {
        "stage": "stage_update_b",
        "category": "timeout",
        "message": "stage_update failed",
    }


def test_wrong_deployment_after_update_reboot_never_runs_rollback(tmp_path):
    FakeBackend.failure_at = "verify_boot_2"
    FakeBackend.failure_category = "wrong_deployment"
    evidence, passed = MODULE.execute_pilot(config(tmp_path), FakeBackend)

    assert not passed
    stages = stage_map(evidence)
    assert stages["warm_boot_b"]["outcome"] == "failed"
    assert evidence["result"]["first_failure"]["category"] == "wrong_deployment"
    assert stages["stage_rollback_a"]["outcome"] == "skipped"
    assert stages["recovery_boot_a"]["outcome"] == "skipped"
    assert "stage_rollback" not in FakeBackend.instances[-1].calls
    assert FakeBackend.instances[-1].calls[-1] == "cleanup"


def test_cleanup_failure_does_not_replace_the_first_failure(tmp_path):
    FakeBackend.failure_at = "stage_update"
    FakeBackend.cleanup_failure = True
    evidence, passed = MODULE.execute_pilot(config(tmp_path), FakeBackend)

    assert not passed
    assert evidence["result"]["first_failure"]["stage"] == "stage_update_b"
    assert evidence["result"]["first_failure"]["category"] == "timeout"
    cleanup = stage_map(evidence)["cleanup"]
    assert cleanup["outcome"] == "failed"
    assert cleanup["details"]["category"] == "cleanup_failed"


def test_cleanup_failure_becomes_first_failure_after_successful_recovery(tmp_path):
    FakeBackend.cleanup_failure = True
    evidence, passed = MODULE.execute_pilot(config(tmp_path), FakeBackend)

    assert not passed
    assert evidence["result"]["first_failure"]["stage"] == "cleanup"
    assert evidence["result"]["first_failure"]["category"] == "cleanup_failed"


def test_real_backend_uses_documented_switch_then_rollback_commands(tmp_path, monkeypatch):
    pilot_config = config(tmp_path)
    backend = MODULE.LocalQemuBackend(pilot_config, [])
    commands = []
    statuses = [
        {"status": {"staged": {"image": {"image": {"image": B, "transport": "registry"}}}}},
        {"status": {"staged": {"image": {"image": {"image": A, "transport": "registry"}}}}},
    ]

    def guest(command, **_kwargs):
        commands.append(command)
        return MODULE.CommandResult(0, "", "")

    monkeypatch.setattr(backend, "guest", guest)
    monkeypatch.setattr(backend, "_status", lambda: statuses.pop(0))

    assert backend.stage_update()["staged_reference"] == B
    assert backend.stage_rollback()["staged_reference"] == A
    assert commands == [f"bootc switch --retain {B}", "bootc rollback"]


def test_retained_command_output_is_bounded():
    value, truncated = MODULE.bounded_text(b"x" * (MODULE.MAX_LOG_BYTES * 2))

    assert truncated
    assert len(value.encode()) <= MODULE.MAX_LOG_BYTES
    assert "output truncated" in value


def test_retained_non_utf8_output_is_bounded_after_json_serialization():
    value, truncated = MODULE.bounded_text(b"\xff\x00" * MODULE.MAX_LOG_BYTES)

    assert truncated
    assert len(json.dumps(value).encode()) - 2 <= MODULE.MAX_LOG_BYTES
    assert "output truncated" in value


@pytest.mark.parametrize(
    ("mutation", "category"),
    [
        ({"Architecture": "arm64"}, "wrong_architecture"),
        ({"Labels": {"containers.bootc": "1"}}, "missing_identity"),
        ({"Digest": "sha256:" + "f" * 64}, "missing_identity"),
    ],
)
def test_image_identity_failures_are_detected_by_real_preflight_code(
    tmp_path, monkeypatch, mutation, category
):
    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    identity = {
        "Digest": "sha256:" + "a" * 64,
        "Architecture": "amd64",
        "Os": "linux",
        "Name": "ghcr.io/tuna-os/skipjack",
        "Labels": {
            "org.opencontainers.image.title": "TunaOS skipjack (gnome)",
            "containers.bootc": "1",
        },
    }
    identity.update(mutation)
    monkeypatch.setattr(backend, "_binary", lambda name: name)
    monkeypatch.setattr(
        backend.runner,
        "run",
        lambda *_args, **_kwargs: MODULE.CommandResult(0, json.dumps(identity), ""),
    )

    with pytest.raises(MODULE.PilotFailure) as error:
        backend._inspect_image(A)

    assert error.value.category == category
