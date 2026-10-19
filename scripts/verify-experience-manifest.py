#!/usr/bin/env python3
"""Validate and compare ISO-builder qualification evidence.

The ISO itself is deliberately treated as an opaque input by the parity gate.
This file validates the small, machine-readable contract emitted alongside it
and compares the CI and browser results before either result can be accepted.

Schema QualificationEvidence/v1 (written by scripts/iso-e2e.sh
--strict-offline-gui as qualification-evidence.json) covers a full offline
GUI qualification: BOTH a plain and a LUKS install driven through the real
bundled installer GUI on egress-blocked QEMU, each followed by an installed
disk boot. The old bare-boolean manifest (variant/flavor/screens/luks/
installed_boot/desktop_contract) is rejected with a migration error.
"""

import argparse
import json
import re
import sys
from pathlib import Path


SCHEMA_V1 = "QualificationEvidence/v1"

# Kept for readers of older evidence and for the walkthrough parity matrix;
# v1 validation no longer keys off these.
REQUIRED_SCREENS = ["welcome", "disk", "encryption", "summary", "install", "done"]
INSTALLER_IDS = {
    "org.bootcinstaller.Installer",
    "org.tunaos.Installer",
    "org.tunaos.InstallerKde",
    "org.tunaos.InstallerCosmic",
    "org.tunaos.InstallerNiri",
    "org.tunaos.InstallerXfce",
}
DIGEST_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")

RESOLVED_INPUT_DIGESTS = ("source", "overlay", "installer", "engine")
OBSERVED_MODES = ("plain", "encrypted")
MEASUREMENT_BLOCKS = ("cold", "warm")

# Top-level fields compared by compare(). Volatile subkeys (wall-clock
# timings, timestamps) are stripped before comparing so two honest runs of
# the same inputs still match.
QUALIFICATION_COMPARE_FIELDS = (
    "variant", "flavor", "platform", "cpu_baseline", "hardware_scope",
    "resolved_inputs", "browser", "offline_network_disabled",
    "observed", "measurements",
)
VOLATILE_SUBKEYS = frozenset({
    "duration_s", "install_duration_s", "cold_boot_s", "warm_boot_s",
    "timestamp", "started_at", "finished_at",
})

MIGRATION_HINT = (
    "not a QualificationEvidence v1 manifest: old bare-boolean manifests "
    "(screens/luks/installed_boot/desktop_contract) are no longer accepted. "
    "Re-run scripts/iso-e2e.sh --strict-offline-gui to generate v1 evidence."
)


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")
    return value


def _require_text(manifest: dict, field: str, label: str) -> None:
    value = manifest.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: {field} must be a non-empty string")


def _require_digest(value, where: str, label: str) -> None:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise ValueError(f"{label}: {where} must be a sha256 digest")


def _require_number(value, where: str, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: {where} must be a number")
    if value < 0:
        raise ValueError(f"{label}: {where} must not be negative")


def _validate_observed_record(
    record, mode: str, label: str, resolved_source: str
) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"{label}: observed.{mode} must be an object")
    for field in ("installed_boot", "desktop_contract"):
        if record.get(field) is not True:
            raise ValueError(f"{label}: observed.{mode}.{field} must be true")
    source = record.get("source_digest")
    booted = record.get("booted_digest")
    _require_digest(source, f"observed.{mode}.source_digest", label)
    _require_digest(booted, f"observed.{mode}.booted_digest", label)
    if source.lower() != resolved_source.lower():
        raise ValueError(
            f"{label}: observed.{mode}.source_digest {source} does not match "
            f"resolved_inputs.source {resolved_source}"
        )
    if source.lower() != booted.lower():
        raise ValueError(
            f"{label}: observed.{mode}: booted digest {booted} does not match "
            f"source digest {source} — the installed system is not running "
            "the qualified image"
        )
    _require_text(record, "target_imgref", f"{label}: observed.{mode}")
    if "duration_s" not in record:
        raise ValueError(f"{label}: observed.{mode}.duration_s is missing")
    _require_number(record["duration_s"], f"observed.{mode}.duration_s", label)


def validate(manifest: dict, label: str) -> None:
    if manifest.get("schema") != SCHEMA_V1:
        raise ValueError(f"{label}: {MIGRATION_HINT}")
    _require_text(manifest, "qualifiedAt", label)
    _require_digest(manifest.get("receiptDigest"), "receiptDigest", label)
    for field in ("variant", "flavor", "platform", "cpu_baseline",
                  "hardware_scope"):
        _require_text(manifest, field, label)
    inputs = manifest.get("resolved_inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"{label}: resolved_inputs must be an object")
    for digest_name in RESOLVED_INPUT_DIGESTS:
        if digest_name not in inputs:
            raise ValueError(
                f"{label}: resolved_inputs.{digest_name} is missing"
            )
        _require_digest(inputs[digest_name],
                        f"resolved_inputs.{digest_name}", label)
    browser = manifest.get("browser")
    if not isinstance(browser, dict):
        raise ValueError(f"{label}: browser must be an object")
    _require_text(browser, "name", f"{label}: browser")
    _require_text(browser, "version", f"{label}: browser")
    # A natively-executed run must not masquerade as browser qualification:
    # a browser.name that declares native (non-browser) provenance fails the
    # manifest even though every other field is well-formed.
    if str(browser["name"]).strip().lower().startswith("native"):
        raise ValueError(
            f"{label}: browser.name {browser['name']!r} declares a native "
            "(non-browser) provenance — a natively-qualified run must not "
            "masquerade as browser qualification"
        )
    for field in ("memory_gib", "free_disk_gib"):
        if field not in browser:
            raise ValueError(f"{label}: browser.{field} is missing")
        _require_number(browser[field], f"browser.{field}", label)
    if manifest.get("offline_network_disabled") is not True:
        raise ValueError(
            f"{label}: offline_network_disabled must be true — "
            "the qualification installs must run with guest egress blocked"
        )
    observed = manifest.get("observed")
    if not isinstance(observed, dict):
        raise ValueError(f"{label}: observed must be an object")
    for mode in OBSERVED_MODES:
        if mode not in observed:
            raise ValueError(
                f"{label}: observed.{mode} is missing — the qualification "
                "must prove BOTH a plain and an encrypted GUI install"
            )
        _validate_observed_record(
            observed[mode], mode, label, inputs["source"]
        )
    measurements = manifest.get("measurements")
    if not isinstance(measurements, dict):
        raise ValueError(f"{label}: measurements must be an object")
    for block in MEASUREMENT_BLOCKS:
        entry = measurements.get(block)
        if not isinstance(entry, dict):
            raise ValueError(
                f"{label}: measurements.{block} must be an object"
            )
        if "duration_s" not in entry:
            raise ValueError(f"{label}: measurements.{block}.duration_s is missing")
        _require_number(entry["duration_s"],
                        f"measurements.{block}.duration_s", label)


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items()
                if k not in VOLATILE_SUBKEYS}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def compare(left: dict, right: dict) -> list[str]:
    return [field for field in QUALIFICATION_COMPARE_FIELDS
            if _stable(left.get(field)) != _stable(right.get(field))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--compare", type=Path, help="compare against a second manifest")
    args = parser.parse_args()
    try:
        first = load(args.manifest)
        validate(first, str(args.manifest))
        if args.compare:
            second = load(args.compare)
            validate(second, str(args.compare))
            differences = compare(first, second)
            if differences:
                raise ValueError(
                    "parity mismatch in: " + ", ".join(differences)
                )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok - validated {args.manifest}")
    if args.compare:
        print(f"ok - {args.manifest} matches {args.compare}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
