#!/usr/bin/env python3
"""Validate and compare ISO-builder experience manifests.

The ISO itself is deliberately treated as an opaque input by the parity gate.
This file validates the small, machine-readable contract emitted alongside it
and compares the CI and browser results before either result can be accepted.
"""

import argparse
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
DIGEST_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")
    return value


def validate(manifest: dict, label: str) -> None:
    required = {
        "variant", "flavor", "source_image_digest", "installer_app_id",
        "screens", "luks", "installed_boot", "desktop_contract",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"{label}: missing fields: {', '.join(missing)}")
    for field in ("variant", "flavor"):
        if not isinstance(manifest[field], str) or not manifest[field].strip():
            raise ValueError(f"{label}: {field} must be a non-empty string")
    digest = manifest["source_image_digest"]
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise ValueError(f"{label}: source_image_digest must be a sha256 digest")
    if manifest["installer_app_id"] not in INSTALLER_IDS:
        raise ValueError(f"{label}: unsupported installer_app_id: {manifest['installer_app_id']}")
    if manifest["screens"] != REQUIRED_SCREENS:
        raise ValueError(
            f"{label}: screens must be exactly {REQUIRED_SCREENS}, got {manifest['screens']!r}"
        )
    for field in ("luks", "installed_boot", "desktop_contract"):
        if manifest[field] is not True:
            raise ValueError(f"{label}: {field} must be true")


def compare(left: dict, right: dict) -> list[str]:
    fields = (
        "variant", "flavor", "source_image_digest", "installer_app_id", "screens",
        "luks", "installed_boot", "desktop_contract",
    )
    return [field for field in fields if left[field] != right[field]]


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
