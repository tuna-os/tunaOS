"""BrowserIsoQualificationReceipt/v1: the evidence behind an ISO cutover (#3381).

tuna-os/iso-builder emits one receipt per browser-built ISO that passed both
strict guest legs (plain and LUKS) of the pinned tunaOS harness, and attests it
with actions/attest-build-provenance. scripts/collect-qualification-receipt.py
authenticates that attestation and commits the receipt's exact canonical bytes
as iso-qualification/receipts/<sha256 hex>.json. scripts/iso-delivery-policy.py
then accepts a cutover target only if its `evidence` names a committed receipt
whose bytes hash to that digest and whose content passes `validate` below.

Both sides share this module so the producer contract has one reader.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .publish_destination import publish_destination

ROOT = Path(__file__).resolve().parents[2]
RECEIPTS_DIR = ROOT / "iso-qualification" / "receipts"

SCHEMA = "BrowserIsoQualificationReceipt/v1"
QUALIFIED = "browser-qualified"
BASIS_PLATFORM = "linux/amd64"
PRODUCER = {
    "repository": "tuna-os/iso-builder",
    "workflow": ".github/workflows/ci.yml",
    "ref": "refs/heads/main",
}
HARNESS_REPOSITORY = "tuna-os/tunaOS"
MODES = ("plain", "luks")
REQUIRED_TRUE = (
    "installed_boot", "desktop_contract", "cold_boot", "warm_boot",
    "media_detached", "boot_arguments_unmodified", "gui_account_created",
    "gui_login",
)
DURATIONS = ("duration_s", "install_duration_s", "cold_boot_s", "warm_boot_s")
PASSPHRASE_PROMPT = {"plain": False, "luks": True}

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
EVIDENCE = DIGEST
COMMIT = re.compile(r"[0-9a-f]{40}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SLUG = r"[A-Za-z0-9][A-Za-z0-9._-]*"


class ReceiptError(ValueError):
    """A receipt is missing, altered, or does not prove a qualified target."""


def canonical(receipt: dict[str, Any]) -> bytes:
    return json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def path_for(evidence: str, receipts_dir: Path = RECEIPTS_DIR) -> Path:
    if not isinstance(evidence, str) or not EVIDENCE.fullmatch(evidence):
        raise ReceiptError(f"evidence {evidence!r} must be sha256:<64 lowercase hex>")
    return receipts_dir / f"{evidence.removeprefix('sha256:')}.json"


def parse(data: bytes) -> dict[str, Any]:
    """Parse receipt bytes and require them to be the canonical encoding."""
    try:
        receipt = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"receipt is not JSON: {exc}") from exc
    if not isinstance(receipt, dict):
        raise ReceiptError("receipt must be a JSON object")
    if canonical(receipt) != data:
        raise ReceiptError("receipt bytes are not the canonical JSON encoding")
    return validate(receipt)


def load(evidence: str, receipts_dir: Path = RECEIPTS_DIR) -> dict[str, Any]:
    """Return the committed receipt that `evidence` names, fully validated."""
    path = path_for(evidence, receipts_dir)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReceiptError(f"evidence {evidence} has no committed receipt: {exc}") from exc
    if digest(data) != evidence:
        raise ReceiptError(f"receipt {path.name} does not hash to {evidence}")
    return parse(data)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReceiptError(message)


def _object(value: Any, where: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{where} must be an object")
    return value


def _text(value: Any, where: str) -> str:
    _require(isinstance(value, str) and bool(value) and value == value.strip(),
             f"{where} must be a non-empty string")
    return value


def _count(value: Any, where: str, minimum: int) -> int:
    _require(type(value) is int and value >= minimum,
             f"{where} must be an integer >= {minimum}")
    return value


def _digest(value: Any, where: str) -> str:
    _require(isinstance(value, str) and bool(DIGEST.fullmatch(value)),
             f"{where} must be sha256:<64 lowercase hex>")
    return value


def _mode(name: str, mode: Any, target: dict[str, Any]) -> None:
    where = f"modes.{name}"
    mode = _object(mode, where)
    _require(mode.get("mode") == name, f"{where}.mode must be {name!r}")
    for field in REQUIRED_TRUE:
        _require(mode.get(field) is True, f"{where}.{field} must be true")
    _require(mode.get("passphrase_prompt") is PASSPHRASE_PROMPT[name],
             f"{where}.passphrase_prompt must be {str(PASSPHRASE_PROMPT[name]).lower()}")
    _require(mode.get("source_digest") == target["imageDigest"],
             f"{where}.source_digest must equal target.imageDigest")
    _require(mode.get("booted_digest") == mode["source_digest"],
             f"{where}.booted_digest must equal source_digest")
    _require(mode.get("target_imgref") == target["image"],
             f"{where}.target_imgref must equal target.image")
    for field in DURATIONS:
        _count(mode.get(field), f"{where}.{field}", 0)
    cold, warm = mode.get("cold_boot_id"), mode.get("warm_boot_id")
    for field, value in (("cold_boot_id", cold), ("warm_boot_id", warm)):
        _require(isinstance(value, str) and bool(UUID.fullmatch(value)),
                 f"{where}.{field} must be a lowercase UUID")
    _require(cold != warm, f"{where} warm boot reused the cold boot ID")


def validate(receipt: dict[str, Any]) -> dict[str, Any]:
    """Apply every contract rule; return the receipt unchanged."""
    _require(receipt.get("schema") == SCHEMA, f"schema must be {SCHEMA!r}")
    _require(receipt.get("qualification") == QUALIFIED,
             f"qualification must be {QUALIFIED!r}")
    qualified_at = receipt.get("qualifiedAt")
    _require(isinstance(qualified_at, str)
             and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", qualified_at)),
             "qualifiedAt must be YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(qualified_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ReceiptError("qualifiedAt is not a valid UTC time") from exc

    target = _object(receipt.get("target"), "target")
    variant = _text(target.get("variant"), "target.variant")
    flavor = _text(target.get("flavor"), "target.flavor")
    _require(target.get("platform") == BASIS_PLATFORM,
             f"target.platform must be {BASIS_PLATFORM!r}")
    # The stock destination is the producer's: a fork's images are not the
    # ones a TunaOS receipt qualified.
    image = f"{publish_destination()}/{variant}:{flavor}"
    _require(target.get("image") == image, f"target.image must be {image}")
    _digest(target.get("imageDigest"), "target.imageDigest")

    iso = _object(receipt.get("iso"), "iso")
    _digest(iso.get("sha256"), "iso.sha256")
    _count(iso.get("sizeBytes"), "iso.sizeBytes", 1)

    producer = _object(receipt.get("producer"), "producer")
    for field, expected in PRODUCER.items():
        _require(producer.get(field) == expected, f"producer.{field} must be {expected!r}")
    _require(isinstance(producer.get("sha"), str) and bool(COMMIT.fullmatch(producer["sha"])),
             "producer.sha must be a 40-hex commit")
    run_id = _count(producer.get("runId"), "producer.runId", 1)
    attempt = _count(producer.get("runAttempt"), "producer.runAttempt", 1)
    _count(producer.get("isoArtifactId"), "producer.isoArtifactId", 1)
    _require(isinstance(producer.get("isoArtifactName"), str)
             and bool(re.fullmatch(rf"iso-{SLUG}-run{run_id}-a{attempt}", producer["isoArtifactName"])),
             "producer.isoArtifactName must be iso-<slug>-run<runId>-a<runAttempt>")

    harness = _object(receipt.get("harness"), "harness")
    _require(harness.get("repository") == HARNESS_REPOSITORY,
             f"harness.repository must be {HARNESS_REPOSITORY!r}")
    _require(isinstance(harness.get("revision"), str) and bool(COMMIT.fullmatch(harness["revision"])),
             "harness.revision must be a 40-hex commit")

    inputs = _object(receipt.get("inputs"), "inputs")
    for field in ("source", "overlay", "installer", "engine"):
        _digest(inputs.get(field), f"inputs.{field}")
    _require(inputs["source"] == target["imageDigest"],
             "inputs.source must equal target.imageDigest")

    modes = _object(receipt.get("modes"), "modes")
    _require(set(modes) == set(MODES), "modes must hold exactly plain and luks")
    for name in MODES:
        _mode(name, modes[name], target)
    return receipt
