#!/usr/bin/env python3
"""Validate ISO build manifests and strict offline GUI qualification receipts."""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


REQUIRED_SCREENS = ["welcome", "disk", "encryption", "summary", "install", "done"]
INSTALLER_IDS = {
    "org.bootcinstaller.Installer",
    "org.tunaos.Installer",
    "org.tunaos.InstallerKde",
    "org.tunaos.InstallerCosmic",
    "org.tunaos.InstallerNiri",
    "org.tunaos.InstallerXfce",
}
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
INSTALLER_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ARCHITECTURES = {"x86_64", "aarch64"}
PLATFORMS = {"linux/amd64": "x86_64", "linux/arm64": "aarch64"}
BUILD_PATHS = {"browser", "ci"}
MANIFEST_KIND = "tunaos-experience-manifest/v2"
RESULT_KIND = "tunaos-offline-gui-result/v1"
RECEIPT_KIND = "tunaos-offline-gui-receipt/v1"

MANIFEST_FIELDS = {
    "kind", "variant", "flavor", "architecture", "platform", "hardware_scope",
    "source_image_ref", "source_image_digest", "base_image_digest",
    "overlay_digest", "iso_sha256", "installer_app_id", "installer_revision",
    "builder_revision", "engine_revision", "build_path", "browser",
    "resource_profile",
}
RESULT_FIELDS = {
    "kind", "profile", "network_disabled", "installer_source",
    "install_method", "generic_cli", "wizard_screens", "installed_boot",
    "desktop_contract", "source_image_digest", "iso_detached", "owned_disk",
    "encrypted", "duration_seconds",
}
QUALIFICATION_FIELDS = RESULT_FIELDS - {"kind", "profile", "duration_seconds"}
RECEIPT_FIELDS = MANIFEST_FIELDS | {"generated_at", "qualification", "timings"}
PARITY_FIELDS = (
    "variant", "flavor", "architecture", "platform", "hardware_scope",
    "source_image_ref", "source_image_digest", "base_image_digest",
    "overlay_digest", "installer_app_id", "installer_revision", "engine_revision",
)


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: document must be a JSON object")
    return value


def _exact_fields(value: dict, expected: set[str], label: str) -> None:
    missing = sorted(expected - value.keys())
    extra = sorted(value.keys() - expected)
    if missing:
        raise ValueError(f"{label}: missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"{label}: unsupported fields: {', '.join(extra)}")


def _string(value: dict, field: str, label: str) -> str:
    result = value[field]
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{label}: {field} must be a non-empty string")
    return result


def _digest(value: dict, field: str, label: str) -> str:
    result = _string(value, field, label)
    if not DIGEST_RE.fullmatch(result):
        raise ValueError(f"{label}: {field} must be a lowercase sha256 digest")
    return result


def _revision(value: dict, field: str, label: str) -> None:
    if not REVISION_RE.fullmatch(_string(value, field, label)):
        raise ValueError(f"{label}: {field} must be a full lowercase git revision")


def validate_manifest(manifest: dict, label: str) -> None:
    _exact_fields(manifest, MANIFEST_FIELDS, label)
    if manifest["kind"] != MANIFEST_KIND:
        raise ValueError(f"{label}: kind must be {MANIFEST_KIND}")
    for field in ("variant", "flavor", "hardware_scope"):
        _string(manifest, field, label)
    if manifest["architecture"] not in ARCHITECTURES:
        raise ValueError(f"{label}: unsupported architecture: {manifest['architecture']}")
    if manifest["platform"] not in PLATFORMS:
        raise ValueError(f"{label}: unsupported platform: {manifest['platform']}")
    if PLATFORMS[manifest["platform"]] != manifest["architecture"]:
        raise ValueError(f"{label}: platform does not match architecture")
    source_digest = _digest(manifest, "source_image_digest", label)
    for field in ("base_image_digest", "overlay_digest", "iso_sha256"):
        _digest(manifest, field, label)
    source_ref = _string(manifest, "source_image_ref", label)
    if not source_ref.endswith(f"@{source_digest}"):
        raise ValueError(
            f"{label}: source_image_ref must be pinned to source_image_digest"
        )
    if manifest["installer_app_id"] not in INSTALLER_IDS:
        raise ValueError(
            f"{label}: unsupported installer_app_id: {manifest['installer_app_id']}"
        )
    if not INSTALLER_REVISION_RE.fullmatch(
        _string(manifest, "installer_revision", label)
    ):
        raise ValueError(
            f"{label}: installer_revision must be a full git or OSTree commit"
        )
    for field in ("builder_revision", "engine_revision"):
        _revision(manifest, field, label)
    if manifest["build_path"] not in BUILD_PATHS:
        raise ValueError(f"{label}: build_path must be browser or ci")
    browser = manifest["browser"]
    if manifest["build_path"] == "browser":
        if not isinstance(browser, dict) or set(browser) != {"name", "version"}:
            raise ValueError(
                f"{label}: browser builds require browser name and version"
            )
        _string(browser, "name", f"{label}.browser")
        _string(browser, "version", f"{label}.browser")
    elif browser is not None:
        raise ValueError(f"{label}: CI builds must set browser to null")
    resources = manifest["resource_profile"]
    expected_resources = {"cpus", "memory_mib", "disk_gib"}
    if not isinstance(resources, dict) or set(resources) != expected_resources:
        raise ValueError(
            f"{label}: resource_profile must contain cpus, memory_mib, disk_gib"
        )
    for field in expected_resources:
        if not isinstance(resources[field], int) or isinstance(resources[field], bool):
            raise ValueError(f"{label}: resource_profile.{field} must be an integer")
        if resources[field] <= 0:
            raise ValueError(f"{label}: resource_profile.{field} must be positive")


def validate_result(result: dict, label: str) -> None:
    _exact_fields(result, RESULT_FIELDS, label)
    if result["kind"] != RESULT_KIND:
        raise ValueError(f"{label}: kind must be {RESULT_KIND}")
    profile = result["profile"]
    if profile not in {"plain", "encrypted"}:
        raise ValueError(f"{label}: profile must be plain or encrypted")
    strict_values = {
        "network_disabled": True,
        "installer_source": "bundled",
        "install_method": "graphical",
        "generic_cli": False,
        "wizard_screens": REQUIRED_SCREENS,
        "installed_boot": True,
        "desktop_contract": True,
        "iso_detached": True,
        "owned_disk": True,
        "encrypted": profile == "encrypted",
    }
    for field, expected in strict_values.items():
        if result[field] != expected:
            raise ValueError(f"{label}: {field} must be {expected!r}")
    _digest(result, "source_image_digest", label)
    duration = result["duration_seconds"]
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        raise ValueError(f"{label}: duration_seconds must be a positive integer")


def build_receipt(manifest: dict, results: list[dict]) -> dict:
    validate_manifest(manifest, "manifest")
    by_profile = {}
    for index, result in enumerate(results):
        validate_result(result, f"result[{index}]")
        profile = result["profile"]
        if profile in by_profile:
            raise ValueError(f"duplicate qualification result for {profile}")
        if result["source_image_digest"] != manifest["source_image_digest"]:
            raise ValueError(
                f"{profile}: installed source digest does not match the manifest"
            )
        by_profile[profile] = result
    if set(by_profile) != {"plain", "encrypted"}:
        missing = sorted({"plain", "encrypted"} - set(by_profile))
        raise ValueError(
            "qualification requires plain and encrypted results"
            + (f"; missing: {', '.join(missing)}" if missing else "")
        )
    qualification = {}
    for profile, result in by_profile.items():
        qualification[profile] = {
            field: value
            for field, value in result.items()
            if field not in {"kind", "profile", "duration_seconds"}
        }
    durations = {
        profile: by_profile[profile]["duration_seconds"]
        for profile in ("plain", "encrypted")
    }
    return {
        **manifest,
        "kind": RECEIPT_KIND,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "qualification": qualification,
        "timings": {
            "plain_seconds": durations["plain"],
            "encrypted_seconds": durations["encrypted"],
            "total_seconds": sum(durations.values()),
        },
    }


def validate_receipt(receipt: dict, label: str) -> None:
    _exact_fields(receipt, RECEIPT_FIELDS, label)
    if receipt["kind"] != RECEIPT_KIND:
        raise ValueError(f"{label}: kind must be {RECEIPT_KIND}")
    manifest = {field: receipt[field] for field in MANIFEST_FIELDS}
    manifest["kind"] = MANIFEST_KIND
    validate_manifest(manifest, label)
    try:
        dt.datetime.fromisoformat(receipt["generated_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label}: generated_at must be an ISO-8601 timestamp") from exc
    qualification = receipt["qualification"]
    if not isinstance(qualification, dict) or set(qualification) != {
        "plain", "encrypted"
    }:
        raise ValueError(
            f"{label}: qualification must contain plain and encrypted results"
        )
    durations = receipt["timings"]
    if not isinstance(durations, dict) or set(durations) != {
        "plain_seconds", "encrypted_seconds", "total_seconds"
    }:
        raise ValueError(f"{label}: timings must contain both legs and total")
    for profile in ("plain", "encrypted"):
        nested = qualification[profile]
        if not isinstance(nested, dict):
            raise ValueError(f"{label}.qualification.{profile}: must be an object")
        _exact_fields(
            nested,
            QUALIFICATION_FIELDS,
            f"{label}.qualification.{profile}",
        )
        result = {
            **nested,
            "kind": RESULT_KIND,
            "profile": profile,
            "duration_seconds": durations[f"{profile}_seconds"],
        }
        validate_result(result, f"{label}.qualification.{profile}")
        if result["source_image_digest"] != receipt["source_image_digest"]:
            raise ValueError(
                f"{label}: {profile} installed source digest does not match receipt"
            )
    if durations["total_seconds"] != (
        durations["plain_seconds"] + durations["encrypted_seconds"]
    ):
        raise ValueError(f"{label}: total_seconds must equal both leg timings")


def validate(value: dict, label: str) -> None:
    kind = value.get("kind")
    if kind == MANIFEST_KIND:
        validate_manifest(value, label)
    elif kind == RECEIPT_KIND:
        validate_receipt(value, label)
    elif kind == RESULT_KIND:
        validate_result(value, label)
    else:
        raise ValueError(f"{label}: unsupported or missing kind: {kind!r}")


def compare(left: dict, right: dict) -> list[str]:
    return [field for field in PARITY_FIELDS if left[field] != right[field]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--compare", type=Path, help="compare parity-critical fields")
    parser.add_argument(
        "--result", action="append", default=[], type=Path,
        help="strict qualification result (exactly plain and encrypted)",
    )
    parser.add_argument("--write-receipt", type=Path)
    args = parser.parse_args()
    try:
        first = load(args.document)
        validate(first, str(args.document))
        if args.result or args.write_receipt:
            if first["kind"] != MANIFEST_KIND:
                raise ValueError("receipts can only be built from an experience manifest")
            if not args.write_receipt:
                raise ValueError("--result requires --write-receipt")
            receipt = build_receipt(first, [load(path) for path in args.result])
            validate_receipt(receipt, str(args.write_receipt))
            args.write_receipt.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"ok - wrote strict qualification receipt {args.write_receipt}")
        if args.compare:
            second = load(args.compare)
            validate(second, str(args.compare))
            differences = compare(first, second)
            if differences:
                raise ValueError("parity mismatch in: " + ", ".join(differences))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok - validated {args.document}")
    if args.compare:
        print(f"ok - {args.document} matches {args.compare}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
