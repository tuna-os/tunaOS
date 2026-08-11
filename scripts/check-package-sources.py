#!/usr/bin/env python3
"""Reject new package-source declarations outside system repos and Tideforge."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

FORBIDDEN_KEYS = {"copr", "ppa", "obs", "aur"}
ALLOWED_REPO_HOSTS = ("repo.tunaos.org", "tideforge.org")


def changed_files(base: str) -> list[Path]:
    output = subprocess.check_output(["git", "diff", "--name-only", f"{base}...HEAD"], text=True)
    return [Path(line) for line in output.splitlines() if line]


def violations(value: object, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in FORBIDDEN_KEYS:
                found.append(f"{key_path}: {key} is not an approved package source")
            found.extend(violations(child, key_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(violations(child, f"{path}[{index}]"))
    elif isinstance(value, str) and path.endswith(".baseurl"):
        if value.startswith(("http://", "https://")) and not any(host in value for host in ALLOWED_REPO_HOSTS):
            found.append(f"{path}: external repository {value!r} is not approved")
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="base revision used to select changed manifests")
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()
    files = changed_files(args.base) if args.base and not args.files else args.files
    manifests = [path for path in files if path.parts[:1] == ("manifests",) and path.suffix in {".yaml", ".yml"}]
    errors: list[str] = []
    for path in manifests:
        try:
            document = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as error:
            errors.append(f"{path}: cannot parse YAML: {error}")
            continue
        errors.extend(f"{path}: {error}" for error in violations(document))
    if errors:
        print("Package source policy violations:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        print("Build missing packages in Tideforge or use the base system repository; see PACKAGE-SOURCING.md.", file=sys.stderr)
        return 1
    print(f"Package source policy OK ({len(manifests)} changed manifest(s) checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
