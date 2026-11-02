#!/usr/bin/env python3
"""Validate immutable image reuse and emit bounded public qualification reports."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

MAX_DOCUMENT_BYTES = 256 * 1024
MAX_EVENT_BYTES = 16 * 1024
MAX_ASSERTIONS = 128
MAX_EVIDENCE = 32
MAX_INPUTS = 512
MAX_TOOLS = 32
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
TOKEN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,79})\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,79}\Z")
UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
STATUSES = frozenset({"passed", "failed", "skipped", "not-run"})
CLASSIFICATIONS = frozenset({"product", "harness", "runner", "unknown"})
REASON_CODES = frozenset({
    "assertion-failed", "cleanup-failed", "contract-mismatch", "malformed-evidence",
    "runner-unavailable", "timeout", "unknown",
})
SKIP_REASON_CODES = frozenset({"blocked-by-prior-failure", "not-applicable"})


class ContractError(ValueError):
    """A closed qualification contract was not satisfied."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def exact(value: object, fields: set[str], where: str) -> dict:
    require(isinstance(value, dict) and set(value) == fields, f"{where}: invalid fields")
    return value


def digest(value: object, where: str) -> str:
    require(isinstance(value, str) and DIGEST.fullmatch(value), f"{where}: expected sha256 digest")
    return value


def token(value: object, where: str) -> str:
    require(isinstance(value, str) and TOKEN.fullmatch(value), f"{where}: expected bounded identifier")
    return value


def timestamp(value: object, where: str) -> str:
    require(isinstance(value, str) and UTC_TIMESTAMP.fullmatch(value),
            f"{where}: expected second-precision UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError(f"{where}: expected second-precision UTC timestamp") from exc
    return value


def https_url(value: object, where: str) -> str:
    require(isinstance(value, str) and len(value) <= 512 and "%" not in value,
            f"{where}: expected bounded public HTTPS URL")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment,
            f"{where}: expected public HTTPS URL without credentials or query data")
    return value


def validate_image(value: object) -> dict:
    image = exact(value, {"manifestDigest", "configDigest"}, "image")
    digest(image["manifestDigest"], "image.manifestDigest")
    digest(image["configDigest"], "image.configDigest")
    return image


def validate_platform(value: object) -> dict:
    platform = exact(value, {"os", "architecture", "variant"}, "platform")
    require(platform["os"] == "linux", "platform.os: only linux is supported")
    token(platform["architecture"], "platform.architecture")
    require(platform["variant"] is None or (isinstance(platform["variant"], str)
            and VERSION.fullmatch(platform["variant"])), "platform.variant: invalid value")
    return platform


def validate_assertion_names(value: object, where: str) -> list[str]:
    require(isinstance(value, list) and 0 < len(value) <= MAX_ASSERTIONS,
            f"{where}: expected a bounded nonempty list")
    names = [token(item, where) for item in value]
    require(len(names) == len(set(names)), f"{where}: duplicate identifier")
    return names


def validate_inputs(value: object) -> dict:
    inputs = exact(value, {"sourceReceipt", "configReceipt", "build", "harness"}, "inputs")
    digest(inputs["sourceReceipt"], "inputs.sourceReceipt")
    digest(inputs["configReceipt"], "inputs.configReceipt")
    build = inputs["build"]
    require(isinstance(build, dict) and 0 < len(build) <= MAX_INPUTS, "inputs.build: invalid inventory")
    for name, value_digest in build.items():
        where = f"inputs.build.{name}"
        token(name, where)
        digest(value_digest, where)
    harness = inputs["harness"]
    require(isinstance(harness, dict) and len(harness) <= MAX_INPUTS, "inputs.harness: invalid inventory")
    for name, record in harness.items():
        where = f"inputs.harness.{name}"
        token(name, where)
        item = exact(record, {"digest", "assertions"}, where)
        digest(item["digest"], f"{where}.digest")
        validate_assertion_names(item["assertions"], f"{where}.assertions")
    return inputs


def validate_tools(value: object) -> dict:
    require(isinstance(value, dict) and 0 < len(value) <= MAX_TOOLS, "tools: invalid inventory")
    for name, record in value.items():
        where = f"tools.{name}"
        token(name, where)
        item = exact(record, {"version", "assertions"}, where)
        require(isinstance(item["version"], str) and VERSION.fullmatch(item["version"]),
                f"{where}.version: expected bounded version")
        validate_assertion_names(item["assertions"], f"{where}.assertions")
    return value


def validate_producer(value: object) -> dict:
    producer = exact(value, {"repository", "workflowPath", "runId", "runAttempt", "runUrl",
                             "artifactId", "artifactName", "artifactUrl", "artifactSha256", "headSha"},
                     "producer")
    require(isinstance(producer["repository"], str) and REPOSITORY.fullmatch(producer["repository"]),
            "producer.repository: invalid slug")
    require(isinstance(producer["workflowPath"], str)
            and re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", producer["workflowPath"]),
            "producer.workflowPath: invalid workflow path")
    require(type(producer["runId"]) is int and producer["runId"] > 0
            and type(producer["runAttempt"]) is int and producer["runAttempt"] > 0
            and type(producer["artifactId"]) is int and producer["artifactId"] > 0,
            "producer: run and artifact IDs must be positive integers")
    require(isinstance(producer["headSha"], str) and COMMIT.fullmatch(producer["headSha"]),
            "producer.headSha: expected full commit")
    token(producer["artifactName"], "producer.artifactName")
    digest(producer["artifactSha256"], "producer.artifactSha256")
    run_url = https_url(producer["runUrl"], "producer.runUrl")
    artifact_url = https_url(producer["artifactUrl"], "producer.artifactUrl")
    base = f"https://github.com/{producer['repository']}/actions/runs/{producer['runId']}"
    require(run_url == base and artifact_url == f"{base}/artifacts/{producer['artifactId']}",
            "producer: run or artifact URL does not match immutable IDs")
    return producer


def validate_verdicts(value: object) -> dict[str, str]:
    require(isinstance(value, dict) and 0 < len(value) <= MAX_ASSERTIONS, "assertions: invalid inventory")
    for name, status in value.items():
        token(name, "assertion name")
        require(status in STATUSES, "assertion status: invalid value")
    return value


def validate_reuse_document(value: object, *, producer: bool, where: str = "reuse receipt") -> dict:
    fields = {"schemaVersion", "image", "inputs", "platform", "tools"}
    if producer:
        fields |= {"producer", "assertions"}
    document = exact(value, fields, where)
    require(document["schemaVersion"] == 1, f"{where}: unsupported schemaVersion")
    validate_image(document["image"])
    validate_inputs(document["inputs"])
    validate_platform(document["platform"])
    validate_tools(document["tools"])
    if producer:
        validate_producer(document["producer"])
        verdicts = validate_verdicts(document["assertions"])
        declared = set(verdicts)
        affected = [record for group in (document["inputs"]["harness"], document["tools"])
                    for record in group.values()]
        require(all(set(record["assertions"]) <= declared for record in affected),
                f"{where}: input or tool names an undeclared assertion")
    return document


def changed_assertions(original: dict, current: dict) -> tuple[list[str], list[str]]:
    changed = []
    affected = set()
    for name in sorted(set(original) | set(current)):
        before = original.get(name)
        after = current.get(name)
        if before != after:
            changed.append(name)
            for record in (before, after):
                if isinstance(record, dict):
                    affected.update(record["assertions"])
    return changed, sorted(affected)


def evaluate_reuse(producer: object, current: object) -> dict:
    previous = validate_reuse_document(producer, producer=True, where="producer receipt")
    expected = validate_reuse_document(current, producer=False, where="current inputs")
    require(previous["image"] == expected["image"], "image identity mismatch; rebuild required")
    require(previous["platform"] == expected["platform"], "platform mismatch; rebuild required")
    for field in ("sourceReceipt", "configReceipt", "build"):
        require(previous["inputs"][field] == expected["inputs"][field],
                f"{field} mismatch; rebuild required")
    harness_changes, invalidated = changed_assertions(previous["inputs"]["harness"],
                                                       expected["inputs"]["harness"])
    tool_changes, tool_assertions = changed_assertions(previous["tools"], expected["tools"])
    invalidated = sorted(set(invalidated) | set(tool_assertions))
    require(len(harness_changes) <= MAX_INPUTS,
            "reuse decision: changed harness inputs exceed bound")
    require(len(tool_changes) <= MAX_TOOLS, "reuse decision: changed tools exceed bound")
    require(len(invalidated) <= MAX_ASSERTIONS,
            "reuse decision: invalidated assertions exceed bound")
    verdicts = dict(previous["assertions"])
    require(set(invalidated) <= set(verdicts),
            "reuse decision: current inputs name an assertion the producer did not declare")
    for name in invalidated:
        verdicts[name] = "not-run"
    result = {
        "schemaVersion": 1,
        "reusable": True,
        "image": previous["image"],
        "sourceReceipt": previous["inputs"]["sourceReceipt"],
        "configReceipt": previous["inputs"]["configReceipt"],
        "producer": previous["producer"],
        "platform": previous["platform"],
        "producerTools": previous["tools"],
        "currentTools": expected["tools"],
        "changedHarnessInputs": harness_changes,
        "changedTools": tool_changes,
        "invalidatedAssertions": invalidated,
        "assertions": verdicts,
    }
    bounded(result, "reuse decision")
    return result


def validate_evidence(value: object) -> dict[str, dict]:
    require(isinstance(value, list) and 0 < len(value) <= MAX_EVIDENCE,
            "evidence: expected bounded nonempty list")
    records = {}
    for raw in value:
        record = exact(raw, {"id", "url", "sha256"}, "evidence entry")
        identifier = token(record["id"], "evidence.id")
        require(identifier not in records, "evidence: duplicate id")
        https_url(record["url"], "evidence.url")
        digest(record["sha256"], "evidence.sha256")
        records[identifier] = record
    return records


def validate_reuse_context(value: object) -> dict:
    reuse = exact(value, {"mode", "producerRunId", "artifactId"}, "reuse")
    require(reuse["mode"] in {"built", "reused"}, "reuse.mode: invalid value")
    if reuse["mode"] == "built":
        require(reuse["producerRunId"] is None and reuse["artifactId"] is None,
                "reuse: built mode cannot name a parent artifact")
    else:
        require(type(reuse["producerRunId"]) is int and reuse["producerRunId"] > 0
                and type(reuse["artifactId"]) is int and reuse["artifactId"] > 0,
                "reuse: reused mode requires immutable parent IDs")
    return reuse


def validate_context(value: object) -> tuple[dict, dict[str, dict]]:
    context = exact(value, {"schemaVersion", "qualificationId", "generatedAt", "image",
                            "sourceReceipt", "configReceipt", "platform", "reuse",
                            "assertions", "evidence", "diagnosticEvidenceId"}, "context")
    require(context["schemaVersion"] == 1, "context: unsupported schemaVersion")
    token(context["qualificationId"], "context.qualificationId")
    timestamp(context["generatedAt"], "context.generatedAt")
    validate_image(context["image"])
    digest(context["sourceReceipt"], "context.sourceReceipt")
    digest(context["configReceipt"], "context.configReceipt")
    validate_platform(context["platform"])
    validate_reuse_context(context["reuse"])
    assertions = validate_assertion_names(context["assertions"], "context.assertions")
    require("diagnostics" not in assertions, "context.assertions: diagnostics is reserved")
    evidence = validate_evidence(context["evidence"])
    diagnostic = token(context["diagnosticEvidenceId"], "context.diagnosticEvidenceId")
    require(diagnostic in evidence, "context.diagnosticEvidenceId: unknown evidence id")
    return context, evidence


def validate_evidence_ids(value: object, evidence: dict[str, dict], where: str) -> list[str]:
    require(isinstance(value, list) and 0 < len(value) <= MAX_EVIDENCE, f"{where}: invalid evidence ids")
    ids = [token(item, where) for item in value]
    require(len(ids) == len(set(ids)) and all(item in evidence for item in ids),
            f"{where}: duplicate or unknown evidence id")
    return ids


def validate_event(value: object, assertions: set[str], evidence: dict[str, dict]) -> dict:
    require(isinstance(value, dict), "event: expected object")
    status = value.get("status")
    common = {"assertion", "status", "timestamp"}
    if status == "passed":
        exact(value, common, "event")
    elif status == "skipped":
        event = exact(value, common | {"reasonCode"}, "event")
        require(isinstance(event["reasonCode"], str)
                and event["reasonCode"] in SKIP_REASON_CODES,
                "event.reasonCode: invalid skip reason")
    elif status == "failed":
        event = exact(value, common | {"failure"}, "event")
        failure = exact(event["failure"], {"classification", "reasonCode", "commandId",
                                             "exitCode", "evidenceIds"}, "event.failure")
        require(isinstance(failure["classification"], str)
                and failure["classification"] in CLASSIFICATIONS,
                "event.failure.classification: invalid value")
        require(isinstance(failure["reasonCode"], str)
                and failure["reasonCode"] in REASON_CODES,
                "event.failure.reasonCode: invalid value")
        require(failure["commandId"] is None or (isinstance(failure["commandId"], str)
                and TOKEN.fullmatch(failure["commandId"])), "event.failure.commandId: invalid value")
        require(failure["exitCode"] is None or (type(failure["exitCode"]) is int
                and -255 <= failure["exitCode"] <= 255), "event.failure.exitCode: invalid value")
        validate_evidence_ids(failure["evidenceIds"], evidence, "event.failure.evidenceIds")
    else:
        raise ContractError("event.status: invalid value")
    assertion = token(value["assertion"], "event.assertion")
    require(assertion in assertions, "event.assertion: undeclared assertion")
    timestamp(value["timestamp"], "event.timestamp")
    return value


def malformed_event(context: dict, at: str | None = None) -> dict:
    return {
        "assertion": "diagnostics",
        "status": "failed",
        "timestamp": at or context["generatedAt"],
        "failure": {
            "classification": "harness",
            "reasonCode": "malformed-evidence",
            "commandId": None,
            "exitCode": None,
            "evidenceIds": [context["diagnosticEvidenceId"]],
        },
    }


def load_events(path: Path, context: dict, evidence: dict[str, dict]) -> list[dict]:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_DOCUMENT_BYTES + 1)
    except OSError:
        return [malformed_event(context)]

    truncated = len(data) > MAX_DOCUMENT_BYTES
    data = data[:MAX_DOCUMENT_BYTES]
    events = []
    seen = set()
    previous_timestamp = None
    declared = set(context["assertions"])
    malformed = False
    for raw_line in data.splitlines():
        malformed_at = previous_timestamp or context["generatedAt"]
        if len(raw_line) > MAX_EVENT_BYTES:
            events.append(malformed_event(context, malformed_at))
            malformed = True
            break
        try:
            line = raw_line.decode("utf-8")
        except UnicodeError:
            events.append(malformed_event(context, malformed_at))
            malformed = True
            break
        if not line.strip():
            continue
        if len(events) >= MAX_ASSERTIONS:
            events.append(malformed_event(context, malformed_at))
            malformed = True
            break
        try:
            event = json.loads(line, object_pairs_hook=unique_object)
            validate_event(event, declared, evidence)
            require(event["assertion"] not in seen, "event stream repeats an assertion")
            require(previous_timestamp is None or event["timestamp"] >= previous_timestamp,
                    "event stream timestamps are out of order")
        except (ContractError, json.JSONDecodeError):
            events.append(malformed_event(context, malformed_at))
            malformed = True
            break
        events.append(event)
        seen.add(event["assertion"])
        previous_timestamp = event["timestamp"]
    if truncated and not malformed:
        events.append(malformed_event(context, previous_timestamp or context["generatedAt"]))
    return events


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("JSON object has duplicate fields")
        result[key] = value
    return result


def assertion_record(name: str, status: str = "not-run", at: str | None = None,
                     classification: str | None = None, reason: str | None = None,
                     command: str | None = None, exit_code: int | None = None,
                     evidence_ids: list[str] | None = None) -> dict:
    return {
        "name": name,
        "status": status,
        "timestamp": at,
        "classification": classification,
        "reasonCode": reason,
        "commandId": command,
        "exitCode": exit_code,
        "evidenceIds": evidence_ids or [],
    }


def build_report(context_value: object, events: list[dict], *, evidence: dict[str, dict] | None = None) -> dict:
    context, validated_evidence = validate_context(context_value)
    if evidence is not None:
        require(evidence == validated_evidence, "build report: evidence does not match context")
    return _build_report_validated(context, events, validated_evidence)


def _build_report_validated(context: dict, events: list[dict],
                            evidence: dict[str, dict]) -> dict:
    records = {name: assertion_record(name) for name in context["assertions"]}

    first_failure = None
    previous_timestamp = None
    for event in events:
        allowed = set(records) | {"diagnostics"}
        validate_event(event, allowed, evidence)
        name = event["assertion"]
        require(name not in records or records[name]["status"] == "not-run",
                "event stream: assertion reported more than once")
        if previous_timestamp is not None:
            require(event["timestamp"] >= previous_timestamp, "event stream: timestamps are out of order")
        previous_timestamp = event["timestamp"]
        if event["status"] == "passed":
            record = assertion_record(name, "passed", event["timestamp"])
        elif event["status"] == "skipped":
            record = assertion_record(name, "skipped", event["timestamp"], reason=event["reasonCode"])
        else:
            failure = event["failure"]
            record = assertion_record(name, "failed", event["timestamp"], failure["classification"],
                                      failure["reasonCode"], failure["commandId"], failure["exitCode"],
                                      failure["evidenceIds"])
            if first_failure is None:
                first_failure = {"stage": name, **{key: record[key] for key in (
                    "timestamp", "classification", "reasonCode", "commandId", "exitCode", "evidenceIds")}}
        records[name] = record
    ordered = [records[name] for name in context["assertions"]]
    if "diagnostics" in records:
        ordered.append(records["diagnostics"])
    counts = {status: sum(record["status"] == status for record in ordered) for status in STATUSES}
    report = {
        "schemaVersion": 1,
        "qualificationId": context["qualificationId"],
        "generatedAt": context["generatedAt"],
        "image": context["image"],
        "sourceReceipt": context["sourceReceipt"],
        "configReceipt": context["configReceipt"],
        "platform": context["platform"],
        "reuse": context["reuse"],
        "releasePass": bool(ordered) and counts["passed"] == len(ordered),
        "summary": counts,
        "assertions": ordered,
        "firstFailure": first_failure,
        "evidence": context["evidence"],
    }
    bounded(report, "qualification report")
    return report


def bounded(value: object, where: str) -> bytes:
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    require(len(encoded) <= MAX_DOCUMENT_BYTES, f"{where}: exceeds size bound")
    return encoded


def load_json(path: Path) -> object:
    with path.open("rb") as stream:
        data = stream.read(MAX_DOCUMENT_BYTES + 1)
    require(len(data) <= MAX_DOCUMENT_BYTES, "JSON document exceeds size bound")
    return json.loads(data, object_pairs_hook=unique_object)


def write_json(path: Path, value: object) -> None:
    encoded = bounded(value, "output document")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    reuse = commands.add_parser("verify-reuse")
    reuse.add_argument("--producer", type=Path, required=True)
    reuse.add_argument("--current", type=Path, required=True)
    reuse.add_argument("--output", type=Path, required=True)
    report = commands.add_parser("report")
    report.add_argument("--context", type=Path, required=True)
    report.add_argument("--events", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify-reuse":
            result = evaluate_reuse(load_json(args.producer), load_json(args.current))
        else:
            context = load_json(args.context)
            validated, evidence = validate_context(context)
            result = _build_report_validated(
                validated, load_events(args.events, validated, evidence), evidence
            )
        write_json(args.output, result)
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: qualification evidence: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
