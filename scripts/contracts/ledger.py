"""Join observed requests with measured native resolution.

This validates consistency, not the authenticity of supplied native proof.
The image/factory gate must obtain that proof from its trusted transaction.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
import re
from typing import Any

from .evidence import EvidenceError, canonical_json, loads, validate
from .targets import validate_target

REQUEST_FIELDS = {"schemaVersion", "kind", "requestId", "target", "phase", "scope", "required", "origin", "startedAt", "manager", "operation", "requests", "options", "coverageGaps"}
RESULT_FIELDS = {"schemaVersion", "kind", "requestId", "finishedAt", "exitCode"}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def inventory_digest(inventory: list[dict]) -> str:
    if not isinstance(inventory, list) or any(not isinstance(item, dict) for item in inventory):
        raise EvidenceError("native inventory must be a list of records")
    return "sha256:" + hashlib.sha256(canonical_json(sorted(inventory, key=canonical_json))).hexdigest()


def _timestamp(value: Any, now: dt.datetime) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError("ledger timestamps must use UTC")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("invalid ledger timestamp") from exc
    if parsed > now:
        raise EvidenceError("future ledger timestamp")
    return parsed


def read_ledger(path: str | Path, target: dict, *, now: dt.datetime | None = None) -> dict:
    validate_target(target)
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise EvidenceError("ledger validation time must be UTC")
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > 32 * 1024 * 1024:
        raise EvidenceError("package request ledger exceeds size limit")
    starts: dict[str, dict] = {}
    results: dict[str, dict] = {}
    gaps = set()
    if path.with_name(path.name + ".gaps").exists():
        gaps.add("request-recording-failed")
    for line in raw.decode("utf-8").splitlines():
        event = loads(line)
        kind = event.get("kind")
        fields = REQUEST_FIELDS if kind == "package-request" else RESULT_FIELDS if kind == "package-result" else None
        if fields is None or set(event) != fields or type(event["schemaVersion"]) is not int or event["schemaVersion"] != 1:
            raise EvidenceError("invalid package ledger event shape")
        request_id = event["requestId"]
        if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise EvidenceError("invalid package request identity")
        if kind == "package-result":
            if request_id in results or request_id not in starts:
                raise EvidenceError("orphan or duplicate package result")
            if type(event["exitCode"]) is not int or not 0 <= event["exitCode"] <= 255:
                raise EvidenceError("invalid package request exit code")
            if _timestamp(event["finishedAt"], now) < _timestamp(starts[request_id]["startedAt"], now):
                raise EvidenceError("package result predates request")
            results[request_id] = event
            continue
        if request_id in starts:
            raise EvidenceError("duplicate package request")
        _timestamp(event["startedAt"], now)
        if event["target"] is None:
            gaps.add("missing-contract-target")
        else:
            validate_target(event["target"])
            if event["target"] != target:
                raise EvidenceError("package request belongs to another target")
        if event["scope"] not in {"final", "transient"} or type(event["required"]) is not bool:
            raise EvidenceError("invalid package request lifecycle")
        if not isinstance(event["phase"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", event["phase"]):
            raise EvidenceError("invalid package request phase")
        origin = event["origin"]
        if not isinstance(origin, dict) or set(origin) != {"path", "line"} or not isinstance(origin["path"], str) or type(origin["line"]) is not int or origin["line"] < 0:
            raise EvidenceError("invalid package request origin")
        for field in ("requests", "options", "coverageGaps"):
            if not isinstance(event[field], list) or any(not isinstance(item, str) or not item for item in event[field]):
                raise EvidenceError("invalid package request argument list")
        if event["manager"] not in {"dnf", "apt", "pacman", "zypper", "portage", "rpm", "dpkg"} or not isinstance(event["operation"], str):
            raise EvidenceError("invalid package request operation")
        gaps.update(event["coverageGaps"])
        starts[request_id] = event
    if not starts:
        gaps.add("missing-package-requests")
    for request_id in starts.keys() - results.keys():
        gaps.add("unfinished-package-request")
    return {"digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "requests": [{**event, "result": results.get(key)} for key, event in starts.items()], "coverageGaps": sorted(gaps)}


def observed_requirements(ledger: dict) -> list[dict]:
    """Preserve base/overlay additions and lifecycle intent, including failures."""
    merged: dict[tuple, dict] = {}
    for event in ledger["requests"]:
        if event["operation"] not in {"install", "in", "reinstall", "downgrade", "build-dep", "builddep"}:
            continue
        for expression in event["requests"]:
            key = (expression, event["manager"], event["scope"])
            origin = {**event["origin"], "phase": event["phase"]}
            item = merged.setdefault(key, {"nativeExpression": expression, "manager": event["manager"], "scope": event["scope"], "required": False, "origins": []})
            item["required"] |= event["required"]
            if origin not in item["origins"]:
                item["origins"].append(origin)
    return sorted(merged.values(), key=canonical_json)


def reconcile(contract: dict, ledger: dict, base_inventory: list[dict], final_inventory: list[dict], native_proof: dict) -> dict:
    """Report unresolved demand; native versions are evaluated by the adapter."""
    validate(contract, "consumer-contract")
    if not isinstance(native_proof, dict):
        raise EvidenceError("native resolution proof must be a record")
    bindings = {"target": contract["target"], "sourceRevision": contract["sourceRevision"], "baseDigest": contract["baseDigest"], "contractDigest": contract["contractDigest"], "requestLedgerDigest": ledger["digest"], "baseInventoryDigest": inventory_digest(base_inventory), "finalInventoryDigest": inventory_digest(final_inventory)}
    for field, expected in bindings.items():
        if native_proof.get(field) != expected:
            raise EvidenceError(f"native resolution disagrees with {field}")
    gaps = set(ledger["coverageGaps"])
    if contract["sourcePolicy"]["forbiddenNew"]:
        gaps.add("forbidden-new-package-source")
    if contract["sourcePolicy"]["policyRevision"] is None:
        gaps.add("missing-policy-revision")
    requirements = {(item["nativeExpression"], item["manager"], item["scope"]): item for item in contract["packageRequirements"]}
    if len(requirements) != len(contract["packageRequirements"]):
        raise EvidenceError("ambiguous native requirement source intents")
    for item in observed_requirements(ledger):
        key = (item["nativeExpression"], item["manager"], item["scope"])
        if key not in requirements:
            gaps.add("unexplained-observed-package-request")
    measured = native_proof.get("requirements", [])
    if not isinstance(measured, list) or any(not isinstance(item, dict) for item in measured):
        raise EvidenceError("native requirement measurements must be records")
    measurements = {}
    for item in measured:
        if any(not isinstance(item.get(field), str) for field in ("nativeExpression", "manager", "scope")):
            raise EvidenceError("invalid native requirement measurement identity")
        key = (item.get("nativeExpression"), item.get("manager"), item.get("scope"))
        if key in measurements:
            raise EvidenceError("duplicate native requirement measurement")
        measurements[key] = item
    final_records = {canonical_json(item) for item in final_inventory}
    for key, requirement in requirements.items():
        measurement = measurements.get(key, {})
        packages = measurement.get("packages", [])
        evidence = measurement.get("evidence", [])
        if not isinstance(packages, list) or any(not isinstance(item, dict) for item in packages) or not isinstance(evidence, list):
            raise EvidenceError("invalid native requirement measurement payload")
        if not evidence or any(not isinstance(item, dict) or not DIGEST.fullmatch(str(item.get("digest", ""))) for item in evidence):
            gaps.add("missing-native-requirement-evidence")
        if measurement.get("status") == "optional-missing" and not requirement["required"]:
            continue
        if measurement.get("status") == "transient-removed" and requirement["scope"] == "transient":
            if any(canonical_json(item) in final_records for item in packages):
                gaps.add("retained-transient-package")
            continue
        if measurement.get("status") != "satisfied" or not packages or any(canonical_json(item) not in final_records for item in packages):
            gaps.add("unsatisfied-final-package-requirement")
        if requirement.get("provider") and measurement.get("provider") != requirement["provider"]:
            gaps.add("native-provider-mismatch")
    dispositions = native_proof.get("requestDispositions", {})
    if not isinstance(dispositions, dict):
        raise EvidenceError("native request dispositions must be a record")
    for event in ledger["requests"]:
        disposition = dispositions.get(event["requestId"])
        allowed = {"satisfied", "approved-replacement", "no-package-mutation"}
        if not event["required"]:
            allowed.add("optional-missing")
        if event["scope"] == "transient":
            allowed.add("transient-removed")
        if disposition not in allowed:
            gaps.add("unresolved-package-request")
    checks = native_proof.get("checks", [])
    if not isinstance(checks, list) or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in checks):
        raise EvidenceError("native resolution checks must be named records")
    by_name = {item.get("name"): item for item in checks if isinstance(item, dict)}
    if len(by_name) != len(checks):
        raise EvidenceError("duplicate native resolution checks")
    for name in {"request-coverage", "native-constraints", "provider-origins", "package-signatures", "dependency-closure", "cpu-baseline"}:
        check = by_name.get(name, {})
        evidence = check.get("evidence", [])
        if not isinstance(evidence, list):
            raise EvidenceError("native check evidence must be a list")
        if check.get("status") != "pass" or not evidence or any(not isinstance(item, dict) or not DIGEST.fullmatch(str(item.get("digest", ""))) for item in evidence):
            gaps.add("missing-native-" + name)
    # Static unresolved operations remain until the pinned native adapter gives
    # measured expansion/transaction evidence for each exact origin.
    resolutions = native_proof.get("resolvedInputs", [])
    if not isinstance(resolutions, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("evidence", []), list) or any(not isinstance(e, dict) for e in entry.get("evidence", [])) for entry in resolutions):
        raise EvidenceError("resolved inputs must carry evidence records")
    for item in contract["resolution"]["unresolved"]:
        if item["code"].startswith(("missing-", "unsupported-", "forbidden-")):
            gaps.add(item["code"])
            continue
        if not any(entry.get("code") == item["code"] and entry.get("origin") == item["origin"] and entry.get("evidence") and all(DIGEST.fullmatch(str(e.get("digest", ""))) for e in entry["evidence"]) for entry in resolutions):
            gaps.add(item["code"])
    return {"schemaVersion": 1, "kind": "demand-resolution", **bindings, "status": "blocked" if gaps else "complete", "reasons": sorted(gaps)}
