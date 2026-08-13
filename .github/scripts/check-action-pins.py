#!/usr/bin/env python3
"""Reject mutable third-party GitHub Actions references."""

from pathlib import Path
import re
import sys


USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def main() -> int:
    errors: list[str] = []
    for path in sorted(Path(".github").rglob("*.yml")) + sorted(
        Path(".github").rglob("*.yaml")
    ):
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            match = USES_RE.match(line)
            if not match:
                continue

            reference = match.group(1)
            # Local composite actions are versioned with this repository.
            if reference.startswith("./") or reference.startswith("docker://"):
                continue

            if "@" not in reference:
                errors.append(f"{path}:{line_number}: missing immutable SHA: {reference}")
                continue

            _, ref = reference.rsplit("@", 1)
            if not SHA_RE.fullmatch(ref):
                errors.append(f"{path}:{line_number}: mutable action ref: {reference}")

    if errors:
        print("GitHub Actions must use full commit SHAs:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1

    print("All third-party GitHub Actions are pinned to full commit SHAs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
