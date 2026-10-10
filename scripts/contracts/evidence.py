"""Strict loaders for the versioned image/factory evidence seam.

Structural validation uses JSON Schema Draft 2020-12 without remote lookup.
Trust in a run's origin and signatures must be established by the caller; a
well-formed receipt alone never authenticates the claims it contains.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any

SCHEMA_ROOT = pathlib.Path(__file__).resolve().parents[2] / "schemas"
KINDS = frozenset({"consumer-contract", "factory-receipt", "image-receipt", "build-health"})


class EvidenceError(ValueError):
    """Malformed or internally inconsistent evidence."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(text: str) -> dict[str, Any]:
    def constant(value: str) -> None:
        raise EvidenceError(f"non-finite JSON number: {value}")
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise EvidenceError(str(exc)) from exc
    if not isinstance(value, dict):
        raise EvidenceError("evidence must be a JSON object")
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def contract_digest(contract: dict[str, Any]) -> str:
    payload = {key: value for key, value in contract.items() if key != "contractDigest"}
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def _schema(name: str) -> dict[str, Any]:
    return loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def _validate(value: Any, schema: dict[str, Any], path: str = "$", current: str = "") -> None:
    from jsonschema import Draft202012Validator, FormatChecker, validators
    from jsonschema import RefResolver

    def reject_remote(uri: str) -> None:
        raise EvidenceError(f"remote schema lookup is forbidden: {uri}")

    identity = _schema("identity.schema.json")
    resolver = RefResolver(
        base_uri="https://schemas.tunaos.org/" + current,
        referrer=schema,
        store={"https://schemas.tunaos.org/identity.schema.json": identity,
               "identity.schema.json": identity},
        handlers={"http": reject_remote, "https": reject_remote, "file": reject_remote},
    )
    type_checker = Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda checker, instance: type(instance) is int)
    strict_validator = validators.extend(Draft202012Validator, type_checker=type_checker)
    validator = strict_validator(schema, resolver=resolver, format_checker=FormatChecker())
    error = next(iter(validator.iter_errors(value)), None)
    if error:
        location = ".".join(str(part) for part in error.absolute_path)
        raise EvidenceError(f"{path}{'.' + location if location else ''}: {error.message}")


def validate_target(target: dict[str, Any]) -> None:
    _validate(target, {"$ref": "identity.schema.json#/$defs/target"})
    from .targets import validate_target as validate_identity
    try:
        validate_identity(target)
    except ValueError as exc:
        raise EvidenceError(str(exc)) from exc


def _unique(items: list[Any], field: str | None, label: str) -> None:
    keys = [canonical_json(item[field] if field else item) for item in items]
    if len(keys) != len(set(keys)):
        raise EvidenceError(f"duplicate {label}")


def _semantic(value: Any, now: dt.datetime) -> None:
    if isinstance(value, dict):
        if "target" in value:
            validate_target(value["target"])
        for key, item in value.items():
            if key in {"startedAt", "measuredAt", "generatedAt"} and item is not None:
                try:
                    stamp = dt.datetime.fromisoformat(item.replace("Z", "+00:00"))
                    if not item.endswith("Z") or stamp.utcoffset() != dt.timedelta(0):
                        raise ValueError("UTC required")
                    if stamp > now:
                        raise ValueError("future evidence timestamp")
                except (ValueError, TypeError) as exc:
                    raise EvidenceError(f"invalid UTC timestamp: {item}") from exc
            _semantic(item, now)
        for field, identity in [("checks", "name"), ("packageRequirements", "name"), ("approvedSources", "id"), ("targets", "target"), ("sources", "id")]:
            if field in value:
                _unique(value[field], identity, field)
        if "requiredChecks" in value:
            _unique(value["requiredChecks"], None, "requiredChecks")
        if "inventory" in value:
            entries = [(item["name"], item["version"], item["architecture"]) for item in value["inventory"]]
            _unique(entries, None, "inventory packages")
    elif isinstance(value, list):
        for item in value:
            _semantic(item, now)


def _document_semantics(document: dict[str, Any]) -> None:
    kind = document["kind"]
    if kind == "consumer-contract":
        if document["baseReference"].rsplit("@", 1)[-1] != document["baseDigest"]:
            raise EvidenceError("base reference and base digest disagree")
    if kind in {"factory-receipt", "image-receipt"}:
        for check in document["checks"]:
            if check["status"] == "pass" and not any(item.get("digest") for item in check["evidence"]):
                raise EvidenceError("passing check requires immutable evidence")
        expected = document["imageDigest"] if kind == "image-receipt" else document["factoryDigest"]
        if document["publication"]["digest"] != expected:
            raise EvidenceError("publication digest disagrees with receipt artifact")
        revision = document["attemptIdentity"]["sourceRevision"]
        if revision != document["provenance"]["sourceRevision"]:
            raise EvidenceError("attempt and provenance source revisions disagree")
        if kind == "image-receipt":
            if revision != document["sourceRevision"]:
                raise EvidenceError("image and attempt source revisions disagree")
            _unique(document["installedPackages"], None, "installed packages")
    if kind == "build-health":
        for row in document["targets"]:
            if row["status"] != "healthy":
                continue
            attempt = row["latestAttempt"]
            readiness = row["packageReadiness"]
            if (document["collection"]["status"] != "available"
                or not row["required"] or not row["scheduled"]
                or attempt is None or attempt["status"] != "success"
                or row["lastVerifiedPublication"] is None
                or row.get("measuredAt") is None or attempt.get("measuredAt") is None
                or readiness.get("measuredAt") is None
                or readiness["status"] != "healthy" or row["contractStatus"] != "pass"):
                raise EvidenceError("healthy target lacks complete successful evidence")
            if any(source["status"] != "available" for source in document["collection"]["sources"]):
                raise EvidenceError("healthy target contradicts unavailable collection source")
            if not attempt.get("imageDigest") or attempt["imageDigest"] != row["lastVerifiedPublication"]["digest"]:
                raise EvidenceError("healthy attempt and publication digest disagree")


def validate(document: dict[str, Any], expected_kind: str | None = None, *, verify_digest: bool = True, now: dt.datetime | None = None) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise EvidenceError("evidence must be an object")
    kind = document.get("kind")
    if not isinstance(kind, str) or kind not in KINDS or (expected_kind and kind != expected_kind):
        raise EvidenceError(f"unexpected evidence kind: {kind!r}")
    _validate(document, _schema(kind + ".schema.json"), current=kind + ".schema.json")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise EvidenceError("validation time must be UTC")
    _semantic(document, now)
    _document_semantics(document)
    if kind == "consumer-contract" and verify_digest and document["contractDigest"] != contract_digest(document):
        raise EvidenceError("consumer contract digest does not match canonical content")
    return document


def load(path: str | pathlib.Path, expected_kind: str | None = None, *, verify_digest: bool = True, now: dt.datetime | None = None) -> dict[str, Any]:
    return validate(loads(pathlib.Path(path).read_text(encoding="utf-8")), expected_kind, verify_digest=verify_digest, now=now)
