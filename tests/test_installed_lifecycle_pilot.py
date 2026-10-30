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
    (ROOT / "schemas/installed-lifecycle-evidence-v1.schema.json").read_text(encoding="utf-8")
)
SPEC = importlib.util.spec_from_file_location("installed_lifecycle_pilot", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

A = "ghcr.io/tuna-os/skipjack@sha256:" + "a" * 64
B = "ghcr.io/tuna-os/skipjack@sha256:" + "b" * 64
DESKTOP_OK = "TUNAOS_DESKTOP_CONTRACT_OK desktop=gnome experience=gnome\n"
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
    boot_override = {}
    staged_override = {}
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
        return {"operation": name} if result is None else result

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
        if name in self.boot_override:
            return self.boot_override[name]
        return {
            "reference": expected,
            "transport": "registry",
            "booted_deployment": {
                "image": {"image": {"image": expected, "transport": "registry"}}
            },
            "desktop_contract": {"outcome": "passed", "stdout": DESKTOP_OK},
        }

    def stage_update(self):
        self._call("stage_update")
        return self.staged_override.get("stage_update", {"staged_reference": B})

    def reboot(self):
        self._call("reboot")

    def stage_rollback(self):
        self._call("stage_rollback")
        return self.staged_override.get("stage_rollback", {"staged_reference": A})

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
    FakeBackend.boot_override = {}
    FakeBackend.staged_override = {}
    FakeBackend.instances = []


def stage_map(evidence):
    return {stage["id"]: stage for stage in evidence["stages"]}


def run_pilot(pilot_config):
    """Run the state machine and require schema-valid evidence for every outcome."""
    evidence, passed = MODULE.execute_pilot(pilot_config, FakeBackend)
    Draft202012Validator(SCHEMA).validate(evidence)
    assert (evidence["result"]["verdict"] == "passed") is passed
    return evidence, passed


def schema_errors(document):
    return list(Draft202012Validator(SCHEMA).iter_errors(document))


def command_schema_errors(events):
    document = {**SCHEMA["properties"]["commands"], "$defs": SCHEMA["$defs"]}
    return list(Draft202012Validator(document).iter_errors(events))


def test_success_is_exact_a_to_b_to_a_and_schema_validates(tmp_path):
    evidence, passed = run_pilot(config(tmp_path))

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


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"image_b": A}, "identical_images"),
        ({"image_a": "ghcr.io/tuna-os/skipjack:gnome"}, "missing_identity"),
        ({"platform": "linux/arm64"}, "wrong_target"),
        ({"confirmed": False}, "safety_confirmation_missing"),
        ({"disk_sha256": "not-a-digest"}, "invalid_input"),
        ({"source_head_sha": "main"}, "missing_identity"),
        ({"source_run_id": ""}, "missing_identity"),
    ],
)
def test_invalid_identity_is_rejected_before_disk_preparation(tmp_path, overrides, category):
    evidence, passed = run_pilot(config(tmp_path, **overrides))

    assert not passed
    assert FakeBackend.instances == []  # Rejected before any backend exists.
    assert evidence["result"]["first_failure"]["category"] == category
    stages = stage_map(evidence)
    assert stages["preflight"]["outcome"] == "failed"
    assert stages["prepare_disk"]["outcome"] == "skipped"
    assert stages["cleanup"] == {
        "id": "cleanup",
        "required": True,
        "outcome": "skipped",
        "details": {"reason": "blocked_by:preflight"},
    }


def test_unexpected_empty_exception_message_still_produces_valid_evidence(tmp_path, monkeypatch):
    def empty_failure(_backend):
        raise AssertionError()

    monkeypatch.setattr(FakeBackend, "preflight", empty_failure)
    evidence, passed = run_pilot(config(tmp_path))

    assert not passed
    assert evidence["result"]["first_failure"] == {
        "stage": "preflight",
        "category": "internal_error",
        "message": "AssertionError",
    }


def test_interruption_persists_incomplete_stage_evidence(tmp_path, monkeypatch):
    snapshots = []

    def interrupt(_backend):
        raise KeyboardInterrupt

    monkeypatch.setattr(FakeBackend, "start_vm", interrupt)
    with pytest.raises(KeyboardInterrupt):
        MODULE.execute_pilot(
            config(tmp_path),
            FakeBackend,
            progress=lambda evidence: snapshots.append(
                json.loads(json.dumps(evidence))
            ),
        )

    latest = snapshots[-1]
    assert latest["result"]["runtime_acceptance"] == "incomplete"
    assert stage_map(latest)["cold_boot_a"]["outcome"] == "pending"
    assert "started_at" in stage_map(latest)["cold_boot_a"]
    assert FakeBackend.instances[-1].calls[-1] == "cleanup"
    assert stage_map(latest)["cleanup"]["outcome"] == "passed"


def test_symlinked_path_ancestors_are_detected(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    assert MODULE.has_symlink_component(linked / "nested" / "file")
    assert not MODULE.has_symlink_component(real / "nested" / "file")
    monkeypatch.chdir(tmp_path)
    assert MODULE.has_symlink_component(Path("linked/nested/file"))
    assert not MODULE.has_symlink_component(Path("real/nested/file"))

def test_interrupted_main_retains_partial_not_final_evidence(tmp_path, monkeypatch):
    pilot_config = config(tmp_path)
    partial = {"result": {"runtime_acceptance": "incomplete"}}

    def interrupt(_config, progress):
        progress(partial)
        raise KeyboardInterrupt

    monkeypatch.setattr(MODULE, "parse_args", lambda _argv: pilot_config)
    monkeypatch.setattr(MODULE, "execute_pilot", interrupt)

    with pytest.raises(KeyboardInterrupt):
        MODULE.main([])

    output = pilot_config.output_dir
    assert not (output / "installed-lifecycle-evidence.json").exists()
    assert json.loads(
        (output / "installed-lifecycle-evidence.partial.json").read_text(
            encoding="utf-8"
        )
    ) == partial


def test_timeout_skips_all_dependent_stages_but_still_cleans_up(tmp_path):
    FakeBackend.failure_at = "stage_update"
    evidence, passed = run_pilot(config(tmp_path))

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
    evidence, passed = run_pilot(config(tmp_path))

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
    evidence, passed = run_pilot(config(tmp_path))

    assert not passed
    assert evidence["result"]["first_failure"]["stage"] == "stage_update_b"
    assert evidence["result"]["first_failure"]["category"] == "timeout"
    cleanup = stage_map(evidence)["cleanup"]
    assert cleanup["outcome"] == "failed"
    assert cleanup["details"]["category"] == "cleanup_failed"


def test_cleanup_failure_becomes_first_failure_after_successful_recovery(tmp_path):
    FakeBackend.cleanup_failure = True
    evidence, passed = run_pilot(config(tmp_path))

    assert not passed
    assert evidence["result"]["first_failure"]["stage"] == "cleanup"
    assert evidence["result"]["first_failure"]["category"] == "cleanup_failed"


@pytest.mark.parametrize(
    ("boot", "details"),
    [
        # Registry/container inspection of B: no booted deployment, no runtime contract.
        (
            "verify_boot_2",
            {"reference": B, "transport": "registry", "labels": {"containers.bootc": "1"}},
        ),
        # No-op update: the guest still boots A after the B update reboot.
        (
            "verify_boot_2",
            {
                "reference": A,
                "transport": "registry",
                "booted_deployment": {"image": {"image": {"image": A}}},
                "desktop_contract": {"outcome": "passed"},
            },
        ),
        # Recovery boot without the runtime desktop contract.
        (
            "verify_boot_3",
            {
                "reference": A,
                "transport": "registry",
                "booted_deployment": {"image": {"image": {"image": A}}},
            },
        ),
        # Cold boot that reports nothing at all.
        ("verify_boot_1", {}),
    ],
)
def test_container_inspection_or_no_op_update_never_counts_as_boot_success(
    tmp_path, boot, details
):
    FakeBackend.boot_override = {boot: details}
    evidence, passed = run_pilot(config(tmp_path))

    assert not passed
    assert evidence["result"]["runtime_acceptance"] == "failed"
    assert evidence["result"]["first_failure"]["category"] == "missing_boot_proof"
    assert stage_map(evidence)["cleanup"]["outcome"] == "passed"


@pytest.mark.parametrize("stage", ["stage_update", "stage_rollback"])
def test_staging_the_wrong_deployment_blocks_the_reboot(tmp_path, stage):
    FakeBackend.staged_override = {stage: {"staged_reference": None}}
    evidence, passed = run_pilot(config(tmp_path))

    assert not passed
    assert evidence["result"]["first_failure"]["category"] == "wrong_deployment"
    assert FakeBackend.instances[-1].calls.count("reboot") == (0 if stage == "stage_update" else 1)


def passing_evidence(tmp_path):
    evidence, passed = run_pilot(config(tmp_path))
    assert passed
    return evidence


@pytest.mark.parametrize("outcome", ["skipped", "failed"])
@pytest.mark.parametrize("stage_index", range(len(MODULE.STAGE_IDS)))
def test_schema_rejects_a_passing_verdict_with_any_unpassed_stage(tmp_path, stage_index, outcome):
    evidence = passing_evidence(tmp_path)
    evidence["stages"][stage_index]["outcome"] = outcome

    assert schema_errors(evidence)


def test_schema_rejects_a_passing_verdict_with_a_missing_stage(tmp_path):
    evidence = passing_evidence(tmp_path)
    del evidence["stages"][4]

    assert schema_errors(evidence)


@pytest.mark.parametrize("stage_id", ["cold_boot_a", "warm_boot_b", "recovery_boot_a"])
def test_schema_rejects_a_passed_boot_stage_without_installed_deployment_proof(
    tmp_path, stage_id
):
    evidence = passing_evidence(tmp_path)
    stage_map(evidence)[stage_id]["details"] = {"reference": A, "labels": {"containers.bootc": "1"}}

    assert schema_errors(evidence)


def test_schema_rejects_a_failed_verdict_without_a_first_failure(tmp_path):
    FakeBackend.failure_at = "stage_update"
    evidence, _passed = run_pilot(config(tmp_path))
    evidence["result"]["first_failure"] = None

    assert schema_errors(evidence)


def test_real_backend_uses_documented_switch_then_rollback_commands(tmp_path, monkeypatch):
    pilot_config = config(tmp_path)
    backend = MODULE.LocalQemuBackend(pilot_config, [])
    commands = []
    statuses = [
        {"status": {"staged": {"image": {"image": {"image": B, "transport": "registry"}}}}},
        {
            "status": {
                "staged": None,
                "rollbackQueued": True,
                "rollback": {"image": {"image": {"image": A, "transport": "registry"}}},
            }
        },
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


def unexecutable_file(directory):
    path = directory / "not-executable"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.parametrize(
    ("make_argv0", "category"),
    [
        (lambda directory: directory / "absent-binary", "missing_dependency"),
        (unexecutable_file, "command_failed"),
    ],
)
def test_commands_that_never_start_are_recorded_and_classified(
    tmp_path, make_argv0, category
):
    events = []

    with pytest.raises(MODULE.PilotFailure) as error:
        MODULE.CommandRunner(events).run(
            [str(make_argv0(tmp_path))], timeout=5, event_name="launch"
        )

    assert error.value.category == category
    assert "could not run" in str(error.value)
    assert len(events) == 1
    assert events[0]["name"] == "launch"
    assert events[0]["returncode"] is None
    assert events[0]["stderr"]
    assert not command_schema_errors(events)


@pytest.mark.parametrize(
    ("mutation", "category"),
    [
        ({"Architecture": "arm64"}, "wrong_architecture"),
        ({"Labels": {"containers.bootc": "1"}}, "missing_identity"),
        ({"Labels": None}, "missing_identity"),
        ({"Labels": []}, "missing_identity"),
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


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds >= 0
        self.now += seconds


def test_wait_for_ssh_never_probes_past_its_deadline(tmp_path, monkeypatch):
    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    clock = FakeClock()
    probe_timeouts = []

    def guest(_command, *, timeout, **_kwargs):
        probe_timeouts.append(timeout)
        clock.now += timeout
        raise MODULE.PilotFailure("timeout", "ssh_probe timed out")

    monkeypatch.setattr(MODULE.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(MODULE.time, "sleep", clock.sleep)
    monkeypatch.setattr(backend, "guest", guest)

    with pytest.raises(MODULE.PilotFailure) as error:
        backend.wait_for_ssh(23)

    assert error.value.category == "timeout"
    # The last probe is clamped to the remaining budget (minimum 1 s), so the
    # whole wait stays within the deadline plus at most that one-second floor.
    assert probe_timeouts and all(t <= 10 for t in probe_timeouts)
    assert clock.now <= 23 + 1



@pytest.mark.parametrize("operation", ["start_vm", "_drain_qemu"])
def test_missing_qemu_preflight_state_is_an_internal_error(tmp_path, operation):
    backend = MODULE.LocalQemuBackend(config(tmp_path), [])

    with pytest.raises(MODULE.PilotFailure) as error:
        getattr(backend, operation)()

    assert error.value.category == "internal_error"

def test_qemu_port_binding_failure_is_classified_from_startup_output(tmp_path):
    class ExitedProcess:
        def poll(self):
            return 1

    class FinishedThread:
        def join(self, timeout=None):
            pass

    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    backend.qemu_process = ExitedProcess()
    backend.qemu_thread = FinishedThread()
    backend.qemu_log.extend(
        b"qemu-system-x86_64: Could not set up host forwarding rule "
        b"'tcp:127.0.0.1:2222-:22'"
    )

    with pytest.raises(MODULE.PilotFailure) as error:
        backend.wait_for_ssh(10)

    assert error.value.category == "port_unavailable"
    assert "2222" in str(error.value)


def test_prepare_disk_creates_the_output_directory(tmp_path, monkeypatch):
    pilot_config = config(tmp_path, output_dir=tmp_path / "nested" / "evidence")
    backend = MODULE.LocalQemuBackend(pilot_config, [])
    vars_source = tmp_path / "OVMF_VARS.fd"
    vars_source.write_bytes(b"vars")
    backend.qemu_bin = "qemu-system-x86_64"
    backend.uefi_code = tmp_path / "OVMF_CODE.fd"
    backend.uefi_vars_source = vars_source
    monkeypatch.setattr(backend, "_binary", lambda name: name)
    monkeypatch.setattr(
        backend.runner, "run", lambda *_args, **_kwargs: MODULE.CommandResult(0, "", "")
    )

    backend.prepare_disk()

    assert (pilot_config.output_dir / "UEFI_VARS.fd").read_bytes() == b"vars"


def test_cleanup_reports_a_qemu_log_drain_that_did_not_stop(tmp_path):
    class ExitedProcess:
        returncode = 0

        def poll(self):
            return 0

    class StuckThread:
        def join(self, timeout=None):
            pass

        def is_alive(self):
            return True

    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    backend.qemu_process = ExitedProcess()
    backend.qemu_thread = StuckThread()

    with pytest.raises(MODULE.PilotFailure) as error:
        backend.cleanup()

    assert error.value.category == "cleanup_failed"
    assert "log drain" in str(error.value)


def test_rollback_requires_the_queued_rollback_deployment_not_a_staged_one(tmp_path, monkeypatch):
    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    monkeypatch.setattr(backend, "guest", lambda *_a, **_k: MODULE.CommandResult(0, "", ""))
    rollback = {"image": {"image": {"image": A, "transport": "registry"}}}
    for status, category in (
        ({"status": {"staged": None, "rollbackQueued": False, "rollback": rollback}}, "wrong_deployment"),
        ({"status": {"staged": None, "rollbackQueued": True}}, "missing_identity"),
        (
            {"status": {"staged": None, "rollbackQueued": True,
                        "rollback": {"image": {"image": {"image": B, "transport": "registry"}}}}},
            "wrong_deployment",
        ),
    ):
        monkeypatch.setattr(backend, "_status", lambda status=status: status)
        with pytest.raises(MODULE.PilotFailure) as error:
            backend.stage_rollback()
        assert error.value.category == category


@pytest.mark.parametrize(
    "stdout",
    [
        "TUNAOS_DESKTOP_CONTRACT_FAIL reason=dm_inactive desktop=gnome\n",
        "TUNAOS_DESKTOP_CONTRACT_OK desktop=gnome experience=gnome\n"
        "TUNAOS_DESKTOP_CONTRACT_FAIL desktop=gnome\n",
        "",
        "TUNAOS_DESKTOP_CONTRACT_OK desktop=kde experience=kde\n",
    ],
)
def test_runtime_verifier_exiting_zero_without_the_gnome_ok_marker_fails(
    tmp_path, monkeypatch, stdout
):
    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    deployment = {"image": {"image": {"image": A, "transport": "registry"}}}
    monkeypatch.setattr(
        backend, "_status", lambda: {"status": {"booted": {"image": deployment["image"]}}}
    )

    def guest(command, **_kwargs):
        if command == "uname -m":
            return MODULE.CommandResult(0, "x86_64\n", "")
        if "os-release" in command:
            return MODULE.CommandResult(0, "skipjack\nskipjack\ngnome-1\n", "")
        return MODULE.CommandResult(0, stdout, "")

    monkeypatch.setattr(backend, "guest", guest)
    with pytest.raises(MODULE.PilotFailure) as error:
        backend.verify_boot(A)
    assert error.value.category == "desktop_contract_failed"


def test_runtime_verifier_with_the_gnome_ok_marker_passes(tmp_path, monkeypatch):
    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    monkeypatch.setattr(
        backend,
        "_status",
        lambda: {"status": {"booted": {"image": {"image": {"image": A, "transport": "registry"}}}}},
    )

    def guest(command, **_kwargs):
        if command == "uname -m":
            return MODULE.CommandResult(0, "x86_64\n", "")
        if "os-release" in command:
            return MODULE.CommandResult(0, "skipjack\nskipjack\ngnome-1\n", "")
        return MODULE.CommandResult(0, DESKTOP_OK, "")

    monkeypatch.setattr(backend, "guest", guest)
    assert backend.verify_boot(A)["desktop_contract"]["stdout"] == DESKTOP_OK


@pytest.mark.parametrize(
    "info",
    [
        {"format": "qcow2", "backing-filename": "/etc/other.qcow2"},
        {"format": "qcow2", "full-backing-filename": "/dev/sda"},
        {"format": "qcow2", "format-specific": {"type": "qcow2", "data": {"data-file": "/dev/sdb"}}},
    ],
)
def test_source_disk_with_backing_or_external_data_file_is_rejected(tmp_path, monkeypatch, info):
    import hashlib

    disk = tmp_path / "installed-a.qcow2"
    disk.write_bytes(b"disk")
    key = tmp_path / "id_ed25519"
    key.write_text("key")
    backend = MODULE.LocalQemuBackend(
        config(tmp_path, disk_sha256=hashlib.sha256(b"disk").hexdigest()), []
    )
    monkeypatch.setattr(backend, "_binary", lambda name: name)
    monkeypatch.setattr(
        backend.runner,
        "run",
        lambda *_a, **_k: MODULE.CommandResult(0, json.dumps(info), ""),
    )
    with pytest.raises(MODULE.PilotFailure) as error:
        backend.preflight()
    assert error.value.category == "unsafe_disk"
    assert "self-contained" in str(error.value)


def test_failing_checkpoint_writer_cannot_block_cleanup_or_hide_the_first_failure(tmp_path):
    started = []

    def progress(_evidence):
        if started:
            raise OSError("disk full")

    class Backend(FakeBackend):
        def start_vm(self):
            started.append(True)
            raise MODULE.PilotFailure("timeout", "boot failed")

    evidence, passed = MODULE.execute_pilot(config(tmp_path), Backend, progress=progress)

    assert not passed
    assert Backend.instances[-1].calls[-1] == "cleanup"
    assert stage_map(evidence)["cleanup"]["outcome"] == "passed"
    assert evidence["result"]["first_failure"]["category"] == "timeout"
    Draft202012Validator(SCHEMA).validate(evidence)


def test_checkpoint_failure_alone_prevents_a_passing_verdict(tmp_path):
    def progress(_evidence):
        raise OSError("disk full")

    evidence, passed = MODULE.execute_pilot(config(tmp_path), FakeBackend, progress=progress)

    assert not passed
    assert FakeBackend.instances[-1].calls[-1] == "cleanup"
    assert evidence["result"]["first_failure"]["category"] == "evidence_write_failed"
    Draft202012Validator(SCHEMA).validate(evidence)


@pytest.mark.parametrize("stage_id", ["cold_boot_a", "warm_boot_b", "recovery_boot_a"])
def test_schema_rejects_unrelated_booted_deployment_proof(tmp_path, stage_id):
    evidence = passing_evidence(tmp_path)
    stage_map(evidence)[stage_id]["details"]["booted_deployment"] = {"unrelated": True}

    assert schema_errors(evidence)


@pytest.mark.parametrize("stage_id", ["cold_boot_a", "warm_boot_b", "recovery_boot_a"])
@pytest.mark.parametrize("stdout", ["", "TUNAOS_DESKTOP_CONTRACT_FAIL desktop=gnome\n"])
def test_schema_rejects_a_passed_desktop_contract_without_the_ok_marker(tmp_path, stage_id, stdout):
    evidence = passing_evidence(tmp_path)
    stage_map(evidence)[stage_id]["details"]["desktop_contract"]["stdout"] = stdout

    assert schema_errors(evidence)


@pytest.mark.parametrize(
    ("stage_id", "wrong"),
    [
        ("warm_boot_b", A),  # no-op update: warm still on A
        ("cold_boot_a", B),
        ("recovery_boot_a", B),
    ],
)
def test_semantic_validation_binds_boot_stages_to_inputs_a_and_b(tmp_path, stage_id, wrong):
    evidence = passing_evidence(tmp_path)
    MODULE.validate_passing_semantics(evidence)
    details = stage_map(evidence)[stage_id]["details"]
    details["reference"] = wrong
    details["booted_deployment"]["image"]["image"]["image"] = wrong

    with pytest.raises(MODULE.PilotFailure) as error:
        MODULE.validate_passing_semantics(evidence)
    assert error.value.category == "wrong_deployment"


def test_semantic_validation_rejects_identical_inputs(tmp_path):
    evidence = passing_evidence(tmp_path)
    evidence["inputs"]["image_b"] = evidence["inputs"]["image_a"]

    with pytest.raises(MODULE.PilotFailure) as error:
        MODULE.validate_passing_semantics(evidence)
    assert error.value.category == "identical_images"


def _boot_backend(tmp_path, monkeypatch, probe_results):
    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    monkeypatch.setattr(
        backend,
        "_status",
        lambda: {"status": {"booted": {"image": {"image": {"image": A, "transport": "registry"}}}}},
    )
    commands = []

    def guest(command, **_kwargs):
        commands.append(command)
        if command == "uname -m":
            return MODULE.CommandResult(0, "x86_64\n", "")
        if "os-release" in command:
            return MODULE.CommandResult(0, "skipjack\nskipjack\ngnome-1\n", "")
        if "display-manager.service" in command and "verify" not in command:
            return MODULE.CommandResult(probe_results.pop(0), "", "")
        return MODULE.CommandResult(0, DESKTOP_OK, "")

    monkeypatch.setattr(backend, "guest", guest)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _s: None)
    return backend, commands


def test_delayed_display_manager_readiness_is_waited_for_before_the_contract(tmp_path, monkeypatch):
    backend, commands = _boot_backend(tmp_path, monkeypatch, [3, 3, 0])

    assert backend.verify_boot(A)["desktop_contract"]["outcome"] == "passed"
    contract_index = next(i for i, c in enumerate(commands) if "verify-desktop-experience" in c)
    assert sum("display-manager.service" in c for c in commands[:contract_index]) == 3
    assert sum("verify-desktop-experience" in c for c in commands) == 1


def test_never_ready_display_manager_still_runs_the_unweakened_contract(tmp_path, monkeypatch):
    backend, _commands = _boot_backend(tmp_path, monkeypatch, [3] * 1000)
    backend.config = MODULE.PilotConfig(**{**backend.config.__dict__, "boot_timeout": 0})
    monkeypatch.setattr(
        backend,
        "guest",
        lambda command, **_k: (
            MODULE.CommandResult(3, "", "") if "display-manager.service" in command
            and "verify" not in command
            else MODULE.CommandResult(0, "x86_64\n", "") if command == "uname -m"
            else MODULE.CommandResult(0, "skipjack\nskipjack\ngnome-1\n", "") if "os-release" in command
            else MODULE.CommandResult(
                0, "TUNAOS_DESKTOP_CONTRACT_FAIL reason=dm_inactive desktop=gnome\n", "")
        ),
    )
    with pytest.raises(MODULE.PilotFailure) as error:
        backend.verify_boot(A)
    assert error.value.category == "desktop_contract_failed"


def test_large_json_output_is_parsed_whole_while_evidence_stays_bounded(tmp_path):
    events = []
    runner = MODULE.CommandRunner(events)
    payload = json.dumps({"RepoTags": ["t" * 20] * 5000, "Digest": "sha256:" + "a" * 64})
    assert len(payload) > 2 * MODULE.MAX_LOG_BYTES

    result = runner.run(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", payload],
        timeout=30,
    )

    assert json.loads(result.stdout)["Digest"] == "sha256:" + "a" * 64
    assert events[-1]["stdout_truncated"] is True
    assert len(events[-1]["stdout"]) < len(payload)


def test_skopeo_inspect_suppresses_tags(tmp_path, monkeypatch):
    backend = MODULE.LocalQemuBackend(config(tmp_path), [])
    seen = []
    monkeypatch.setattr(backend, "_binary", lambda name: name)

    def run(argv, **_kwargs):
        seen.append(argv)
        raise MODULE.PilotFailure("command_failed", "stop")

    monkeypatch.setattr(backend.runner, "run", run)
    with pytest.raises(MODULE.PilotFailure):
        backend._inspect_image(A)
    assert "--no-tags" in seen[0]


def test_dangling_symlink_pilot_state_is_rejected_by_preflight(tmp_path, monkeypatch):
    import hashlib

    pilot_config = config(tmp_path, disk_sha256=hashlib.sha256(b"disk").hexdigest())
    (tmp_path / "installed-a.qcow2").write_bytes(b"disk")
    (tmp_path / "id_ed25519").write_text("key")
    pilot_config.output_dir.mkdir()
    outside = tmp_path / "outside.fd"
    (pilot_config.output_dir / "UEFI_VARS.fd").symlink_to(outside)
    backend = MODULE.LocalQemuBackend(pilot_config, [])
    monkeypatch.setattr(backend, "_binary", lambda name: name)

    with pytest.raises(MODULE.PilotFailure) as error:
        backend.preflight()
    assert error.value.category == "unsafe_disk"
    assert not outside.exists()
