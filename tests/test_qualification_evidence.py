"""Immutable reuse and bounded first-failure evidence contracts for #3476."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qualification_evidence", ROOT / "scripts/qualification-evidence.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
D = {letter: "sha256:" + letter * 64 for letter in "abcdef123456789"}


def producer_receipt() -> dict:
    return {
        "schemaVersion": 1,
        "image": {"manifestDigest": D["a"], "configDigest": D["b"]},
        "inputs": {
            "sourceReceipt": D["c"],
            "configReceipt": D["d"],
            "build": {
                "config-assets": D["1"],
                "engine-pin": D["2"],
                "installer-pin": D["3"],
                "overlay-pin": D["4"],
                "package-sources": D["5"],
            },
            "harness": {
                "installer-driver": {"digest": D["6"], "assertions": ["install", "target-reboot"]},
                "login-probe": {"digest": D["7"], "assertions": ["login"]},
            },
        },
        "producer": {
            "repository": "tuna-os/tunaOS",
            "workflowPath": ".github/workflows/fork-image-qualification.yml",
            "runId": 123,
            "runAttempt": 2,
            "runUrl": "https://github.com/tuna-os/tunaOS/actions/runs/123",
            "artifactId": 456,
            "artifactName": "fork-image-yellowfin",
            "artifactUrl": "https://github.com/tuna-os/tunaOS/actions/runs/123/artifacts/456",
            "artifactSha256": D["8"],
            "headSha": "a" * 40,
        },
        "platform": {"os": "linux", "architecture": "amd64", "variant": None},
        "tools": {
            "podman": {"version": "5.6.1", "assertions": ["build", "install"]},
            "qemu": {"version": "10.1.0", "assertions": ["boot", "login", "install", "target-reboot"]},
        },
        "assertions": {
            "build": "passed", "boot": "passed", "login": "passed",
            "install": "passed", "target-reboot": "passed",
        },
    }


def current_inputs() -> dict:
    value = producer_receipt()
    return {key: copy.deepcopy(value[key]) for key in
            ("schemaVersion", "image", "inputs", "platform", "tools")}


def evidence_context() -> dict:
    return {
        "schemaVersion": 1,
        "qualificationId": "yellowfin-gnome-amd64",
        "generatedAt": "2026-10-20T06:00:00Z",
        "image": {"manifestDigest": D["a"], "configDigest": D["b"]},
        "sourceReceipt": D["c"],
        "configReceipt": D["d"],
        "platform": {"os": "linux", "architecture": "amd64", "variant": None},
        "reuse": {"mode": "reused", "producerRunId": 123, "artifactId": 456},
        "assertions": ["build", "boot", "login", "welcome", "install", "target-reboot", "cleanup"],
        "evidence": [
            {"id": "run-log", "url": "https://github.com/tuna-os/tunaOS/actions/runs/789", "sha256": D["8"]},
            {"id": "screenshots", "url": "https://github.com/tuna-os/tunaOS/actions/runs/789/artifacts/987", "sha256": D["9"]},
        ],
        "diagnosticEvidenceId": "run-log",
    }


def event(name: str, status: str, second: int, **failure) -> dict:
    value = {"assertion": name, "status": status, "timestamp": f"2026-10-20T06:00:{second:02d}Z"}
    if status == "failed":
        value["failure"] = {
            "classification": failure.get("classification", "product"),
            "reasonCode": failure.get("reason", "assertion-failed"),
            "commandId": failure.get("command", "qualification-step"),
            "exitCode": failure.get("exit_code", 1),
            "evidenceIds": failure.get("evidence", ["run-log"]),
        }
    elif status == "skipped":
        value["reasonCode"] = failure.get("reason", "blocked-by-prior-failure")
    return value


def test_exact_immutable_receipt_allows_reuse_and_preserves_parent_identity():
    result = MODULE.evaluate_reuse(producer_receipt(), current_inputs())
    assert result["reusable"] is True
    assert result["image"] == producer_receipt()["image"]
    assert result["producer"]["runId"] == 123
    assert result["producer"]["artifactId"] == 456
    assert result["producer"]["artifactSha256"] == D["8"]
    assert result["platform"] == {"os": "linux", "architecture": "amd64", "variant": None}
    assert result["producerTools"]["qemu"]["version"] == "10.1.0"
    assert result["invalidatedAssertions"] == []


@pytest.mark.parametrize("field", ["sourceReceipt", "configReceipt"])
def test_missing_or_mismatched_receipts_fail_closed(field):
    current = current_inputs()
    if field == "sourceReceipt":
        del current["inputs"][field]
        match = "invalid fields"
    else:
        current["inputs"][field] = D["9"]
        match = "rebuild required"
    with pytest.raises(MODULE.ContractError, match=match):
        MODULE.evaluate_reuse(producer_receipt(), current)


@pytest.mark.parametrize("name", [
    "config-assets", "engine-pin", "installer-pin", "overlay-pin", "package-sources",
])
def test_every_consumed_build_input_mutation_forces_rebuild(name):
    current = current_inputs()
    current["inputs"]["build"][name] = D["9"]
    with pytest.raises(MODULE.ContractError, match="rebuild required"):
        MODULE.evaluate_reuse(producer_receipt(), current)


def test_mutable_or_missing_image_identity_fails_closed():
    for image in ({"manifestDigest": "latest", "configDigest": D["b"]},
                  {"configDigest": D["b"]},
                  {"manifestDigest": D["a"], "configDigest": D["9"]}):
        current = current_inputs()
        current["image"] = image
        with pytest.raises(MODULE.ContractError):
            MODULE.evaluate_reuse(producer_receipt(), current)


def test_harness_only_change_reuses_bytes_but_invalidates_only_affected_verdicts():
    current = current_inputs()
    current["inputs"]["harness"]["installer-driver"]["digest"] = D["9"]
    result = MODULE.evaluate_reuse(producer_receipt(), current)
    assert result["reusable"] is True
    assert result["changedHarnessInputs"] == ["installer-driver"]
    assert result["invalidatedAssertions"] == ["install", "target-reboot"]
    assert result["assertions"] == {
        "build": "passed", "boot": "passed", "login": "passed",
        "install": "not-run", "target-reboot": "not-run",
    }


def test_tool_version_change_invalidates_declared_tests_without_rebuilding_image():
    current = current_inputs()
    current["tools"]["qemu"]["version"] = "10.2.0"
    result = MODULE.evaluate_reuse(producer_receipt(), current)
    assert result["reusable"] is True
    assert result["changedTools"] == ["qemu"]
    assert result["invalidatedAssertions"] == ["boot", "install", "login", "target-reboot"]
    assert result["producerTools"]["qemu"]["version"] == "10.1.0"
    assert result["currentTools"]["qemu"]["version"] == "10.2.0"


@pytest.mark.parametrize("mutation", ["repository", "run-url", "artifact-url", "artifact-hash", "head", "platform"])
def test_parent_run_artifact_and_platform_are_strict(mutation):
    receipt = producer_receipt()
    if mutation == "repository":
        receipt["producer"]["repository"] = "other/repo"
    elif mutation == "run-url":
        receipt["producer"]["runUrl"] += "/attempts/2"
    elif mutation == "artifact-url":
        receipt["producer"]["artifactUrl"] = "https://example.invalid/artifact"
    elif mutation == "artifact-hash":
        receipt["producer"]["artifactSha256"] = "latest"
    elif mutation == "head":
        receipt["producer"]["headSha"] = "abc123"
    else:
        receipt["platform"]["architecture"] = "arm64"
    with pytest.raises(MODULE.ContractError):
        MODULE.evaluate_reuse(receipt, current_inputs())

def test_producer_inputs_and_tools_only_invalidate_declared_assertions():
    receipt = producer_receipt()
    receipt["inputs"]["harness"]["installer-driver"]["assertions"].append("undeclared")
    with pytest.raises(MODULE.ContractError, match="undeclared assertion"):
        MODULE.evaluate_reuse(receipt, current_inputs())


def test_first_failure_survives_later_cleanup_failure():
    report = MODULE.build_report(evidence_context(), [
        event("build", "passed", 1),
        event("install", "failed", 2, classification="product", command="native-installer", exit_code=7),
        event("cleanup", "failed", 3, classification="harness", reason="cleanup-failed", command="vm-cleanup"),
    ])
    assert report["firstFailure"] == {
        "stage": "install", "timestamp": "2026-10-20T06:00:02Z",
        "classification": "product", "reasonCode": "assertion-failed",
        "commandId": "native-installer", "exitCode": 7, "evidenceIds": ["run-log"],
    }
    assert next(row for row in report["assertions"] if row["name"] == "cleanup")["classification"] == "harness"
    assert report["releasePass"] is False


@pytest.mark.parametrize("classification", ["product", "harness", "runner", "unknown"])
def test_failure_classification_is_evidence_backed_and_never_a_release_pass(classification):
    report = MODULE.build_report(evidence_context(), [
        event("boot", "failed", 1, classification=classification,
              reason="unknown" if classification == "unknown" else "assertion-failed")
    ])
    assert report["firstFailure"]["classification"] == classification
    assert report["firstFailure"]["evidenceIds"] == ["run-log"]
    assert report["releasePass"] is False


def test_classification_without_retained_evidence_is_rejected():
    bad = event("boot", "failed", 1)
    bad["failure"]["evidenceIds"] = []
    with pytest.raises(MODULE.ContractError, match="evidence"):
        MODULE.build_report(evidence_context(), [bad])


def test_timeout_has_bounded_command_exit_and_evidence():
    report = MODULE.build_report(evidence_context(), [
        event("boot", "failed", 1, classification="runner", reason="timeout",
              command="qemu-boot", exit_code=None)
    ])
    assert report["firstFailure"] == {
        "stage": "boot", "timestamp": "2026-10-20T06:00:01Z",
        "classification": "runner", "reasonCode": "timeout", "commandId": "qemu-boot",
        "exitCode": None, "evidenceIds": ["run-log"],
    }


def test_public_report_lists_pass_fail_skip_and_never_run_with_exact_image():
    report = MODULE.build_report(evidence_context(), [
        event("build", "passed", 1), event("boot", "failed", 2),
        event("login", "skipped", 3), event("cleanup", "passed", 4),
    ])
    statuses = {row["name"]: row["status"] for row in report["assertions"]}
    assert statuses == {
        "build": "passed", "boot": "failed", "login": "skipped", "welcome": "not-run",
        "install": "not-run", "target-reboot": "not-run", "cleanup": "passed",
    }
    assert report["summary"] == {"passed": 2, "failed": 1, "skipped": 1, "not-run": 3}
    assert report["image"] == evidence_context()["image"]
    assert report["reuse"] == {"mode": "reused", "producerRunId": 123, "artifactId": 456}


def test_welcome_screenshot_never_counts_as_install_success():
    report = MODULE.build_report(evidence_context(), [
        event("build", "passed", 1), event("boot", "passed", 2),
        event("login", "passed", 3), event("welcome", "passed", 4),
    ])
    assert next(row for row in report["assertions"] if row["name"] == "install")["status"] == "not-run"
    assert report["releasePass"] is False


def test_malformed_log_becomes_safe_harness_failure_without_echoing_private_data(tmp_path):
    context = evidence_context()
    path = tmp_path / "events.jsonl"
    path.write_text('{"password":"hunter2","path":"/home/runner/private","environment":{"TOKEN":"secret"}}\n')
    evidence = MODULE.validate_context(context)[1]
    report = MODULE.build_report(context, MODULE.load_events(path, context, evidence))
    encoded = json.dumps(report)
    assert report["firstFailure"]["stage"] == "diagnostics"
    assert report["firstFailure"]["classification"] == "harness"
    assert report["firstFailure"]["reasonCode"] == "malformed-evidence"
    for private in ("hunter2", "/home/runner/private", "TOKEN", "secret", "password", "environment"):
        assert private not in encoded

@pytest.mark.parametrize("corruption", ["malformed", "duplicate", "out-of-order"])
def test_bad_event_after_valid_result_adds_diagnostic_without_hiding_first_failure(tmp_path, corruption):
    context = evidence_context()
    rows = [event("install", "failed", 2), event("cleanup", "passed", 3)]
    if corruption == "malformed":
        encoded = json.dumps(rows[0]) + "\n{not-json}\n"
    elif corruption == "duplicate":
        encoded = "\n".join(map(json.dumps, [rows[0], rows[0]])) + "\n"
    else:
        encoded = "\n".join(map(json.dumps, [rows[0], event("cleanup", "passed", 1)])) + "\n"
    path = tmp_path / "events.jsonl"
    path.write_text(encoded)
    evidence = MODULE.validate_context(context)[1]
    report = MODULE.build_report(context, MODULE.load_events(path, context, evidence))
    assert report["firstFailure"]["stage"] == "install"
    diagnostics = next(row for row in report["assertions"] if row["name"] == "diagnostics")
    assert diagnostics["classification"] == "harness"
    assert diagnostics["reasonCode"] == "malformed-evidence"


@pytest.mark.parametrize("field,value", [
    ("message", "user Alice password hunter2"),
    ("environment", {"TOKEN": "secret"}),
    ("path", "/home/runner/private"),
])
def test_event_schema_has_no_free_form_secret_or_host_path_channel(field, value):
    bad = event("boot", "failed", 1)
    bad[field] = value
    with pytest.raises(MODULE.ContractError, match="invalid fields"):
        MODULE.build_report(evidence_context(), [bad])


def test_document_and_event_size_limits_fail_closed(tmp_path, monkeypatch):
    context = evidence_context()
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"x" * (MODULE.MAX_DOCUMENT_BYTES + 1))
    evidence = MODULE.validate_context(context)[1]
    report = MODULE.build_report(context, MODULE.load_events(path, context, evidence))
    assert report["firstFailure"]["reasonCode"] == "malformed-evidence"
    oversized_json = tmp_path / "receipt.json"
    oversized_json.write_bytes(b"x" * (MODULE.MAX_DOCUMENT_BYTES + 1))
    with pytest.raises(MODULE.ContractError, match="size bound"):
        MODULE.load_json(oversized_json)
    monkeypatch.setattr(MODULE, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(MODULE.ContractError, match="size bound"):
        MODULE.build_report(context, [])


def test_schemas_accept_receipts_decision_and_public_report():
    reuse_schema = json.loads((ROOT / "schemas/qualification-reuse-v1.schema.json").read_text())
    report_schema = json.loads((ROOT / "schemas/qualification-report-v1.schema.json").read_text())
    Draft202012Validator.check_schema(reuse_schema)
    Draft202012Validator.check_schema(report_schema)
    reuse_validator = Draft202012Validator(reuse_schema)
    for value in (producer_receipt(), current_inputs(), MODULE.evaluate_reuse(producer_receipt(), current_inputs())):
        reuse_validator.validate(value)
    report = MODULE.build_report(evidence_context(), [event("build", "passed", 1)])
    report_validator = Draft202012Validator(report_schema)
    report_validator.validate(report)
    leaked = {**report, "environment": {"TOKEN": "secret"}}
    assert not report_validator.is_valid(leaked)
    failed_without_evidence = MODULE.build_report(evidence_context(), [event("boot", "failed", 1)])
    failed_without_evidence["firstFailure"]["evidenceIds"] = []
    assert not report_validator.is_valid(failed_without_evidence)


def test_duplicate_json_fields_are_rejected_without_last_value_wins(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text('{"schemaVersion":1,"schemaVersion":1}')
    with pytest.raises(MODULE.ContractError, match="duplicate"):
        MODULE.load_json(path)


def test_schema_rejects_credentialed_or_encoded_public_urls():
    schema = json.loads((ROOT / "schemas/qualification-report-v1.schema.json").read_text())
    validator = Draft202012Validator(schema)
    report = MODULE.build_report(evidence_context(), [event("build", "passed", 1)])
    for url in (
        "https://user:secret@example.org/log",
        "https://example.org/log?token=secret",
        "https://example.org/log#private",
        "https://example.org/log%2Fprivate",
    ):
        candidate = copy.deepcopy(report)
        candidate["evidence"][0]["url"] = url
        assert not validator.is_valid(candidate)


def test_disjoint_tool_inventories_are_bounded_before_serialization():
    producer = producer_receipt()
    producer["tools"] = {
        f"tool-{index}": {"version": "1.0.0", "assertions": ["build"]}
        for index in range(32)
    }
    current = current_inputs()
    current["tools"] = {
        f"current-{index}": {"version": "1.0.0", "assertions": ["build"]}
        for index in range(32)
    }
    with pytest.raises(MODULE.ContractError, match="changed tools exceed bound"):
        MODULE.evaluate_reuse(producer, current)


def test_disjoint_harness_inventories_are_bounded_before_serialization():
    producer = producer_receipt()
    producer["inputs"]["harness"] = {
        f"producer-harness-{index}": {"digest": D["6"], "assertions": ["build"]}
        for index in range(512)
    }
    current = current_inputs()
    current["inputs"]["harness"] = {
        f"current-harness-{index}": {"digest": D["7"], "assertions": ["build"]}
        for index in range(512)
    }
    with pytest.raises(MODULE.ContractError, match="changed harness inputs exceed bound"):
        MODULE.evaluate_reuse(producer, current)


@pytest.mark.parametrize("field,value", [("classification", []), ("reasonCode", {})])
def test_malformed_failure_enum_is_reported_after_a_valid_failure(tmp_path, field, value):
    context = evidence_context()
    rows = [event("install", "failed", 1), event("cleanup", "failed", 2)]
    rows[1]["failure"][field] = value
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(map(json.dumps, rows)) + "\n")
    report = MODULE.build_report(context, MODULE.load_events(path, context, MODULE.validate_context(context)[1]))
    assert report["firstFailure"]["stage"] == "install"
    assert any(row["name"] == "diagnostics" for row in report["assertions"])


@pytest.mark.parametrize("tail", [b"x" * (MODULE.MAX_DOCUMENT_BYTES + 1), b"\xff"])
def test_malformed_tail_preserves_prior_failure(tmp_path, tail):
    context = evidence_context()
    prefix = (json.dumps(event("install", "failed", 1)) + "\n").encode()
    path = tmp_path / "events.jsonl"
    path.write_bytes(prefix + tail)
    report = MODULE.build_report(context, MODULE.load_events(path, context, MODULE.validate_context(context)[1]))
    assert report["firstFailure"]["stage"] == "install"
    assert any(row["name"] == "diagnostics" for row in report["assertions"])


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        ("build", "inputs.build.bad.digest"),
        ("harness", "inputs.harness.bad.digest"),
    ],
)
def test_validation_errors_identify_the_offending_input(mutation, path):
    receipt = producer_receipt()
    if mutation == "build":
        receipt["inputs"]["build"]["bad"] = "not-a-digest"
    else:
        receipt["inputs"]["harness"]["bad"] = {"digest": "not-a-digest", "assertions": ["build"]}
    with pytest.raises(MODULE.ContractError, match=re.escape(path)):
        MODULE.evaluate_reuse(receipt, current_inputs())


def test_build_report_revalidates_context_when_evidence_is_supplied():
    context = evidence_context()
    evidence = MODULE.validate_context(context)[1]
    del context["image"]
    with pytest.raises(MODULE.ContractError, match="invalid fields"):
        MODULE.build_report(context, [], evidence=evidence)
