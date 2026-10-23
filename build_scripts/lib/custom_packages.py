#!/usr/bin/env python3
"""Parse and validate custom/packages.yaml through the repository YAML tool."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


ALLOWED_KEYS = frozenset(
    {"apt", "dnf", "zypper", "pacman", "emerge", "optional", "copr", "flatpak"}
)


class CustomPackageConfigError(ValueError):
    """Raised when custom/packages.yaml violates its published contract."""


def validate_document(document: Any, source: Path) -> dict[str, list[str]]:
    """Validate normalized YAML and return its package-list mapping."""
    if not isinstance(document, dict):
        raise CustomPackageConfigError(f"{source}: root must be a mapping")

    validated: dict[str, list[str]] = {}
    for key, values in document.items():
        if not isinstance(key, str) or key not in ALLOWED_KEYS:
            raise CustomPackageConfigError(
                f"{source}: unsupported key {key!r}; expected one of "
                f"{', '.join(sorted(ALLOWED_KEYS))}"
            )
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise CustomPackageConfigError(
                f"{source}: {key!r} must be a non-empty-string list"
            )
        validated[key] = values
    return validated


def load_document(
    path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, list[str]]:
    """Load YAML through yq, then validate the normalized JSON document."""
    yq = os.environ.get("YQ") or shutil.which("yq")
    if not yq:
        raise CustomPackageConfigError(
            "custom/packages.yaml requires yq; install repository build tools first"
        )

    try:
        result = runner(
            [yq, "-o=json", ".", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise CustomPackageConfigError(f"{path}: cannot run yq: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise CustomPackageConfigError(
            f"{path}: invalid YAML{f': {detail}' if detail else ''}"
        )
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CustomPackageConfigError(f"{path}: yq returned invalid JSON: {exc}") from exc
    return validate_document(document, path)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--items", metavar="KEY")
    parser.add_argument("path", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        document = load_document(args.path)
    except (OSError, CustomPackageConfigError) as exc:
        print(f"custom/packages.yaml: {exc}", file=sys.stderr)
        return 1

    if args.items is not None:
        for value in document.get(args.items, []):
            print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
