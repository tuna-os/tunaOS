#!/usr/bin/env python3
"""Print `name==version` for pins in image-versions.yaml `python_packages`.

CI runs this before the YAML parser exists, so it reads the section with a
scoped text match. Other sections may reuse a package name at another version
(`downloads.jsonschema`), so a whole-file match is wrong.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SECTION = "python_packages"


def read_pins(text: str, names: list[str]) -> list[str]:
    section = re.search(
        r"^" + SECTION + r":[ \t]*\n((?:[ \t]+[^\n]*\n|[ \t]*\n)*)", text, re.M
    )
    if section is None:
        raise ValueError(f"missing {SECTION} section")
    specs = []
    for name in names:
        matches = re.findall(
            r'^  ' + re.escape(name) + r': "([0-9.]+)"[ \t]*$', section.group(1), re.M
        )
        if len(matches) != 1:
            raise ValueError(f"missing or ambiguous {SECTION} pin: {name}")
        specs.append(f"{name}=={matches[0]}")
    return specs


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python-package-pins.py VERSIONS_FILE NAME...", file=sys.stderr)
        return 2
    try:
        specs = read_pins(Path(argv[1]).read_text(), argv[2:])
    except ValueError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("\n".join(specs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
