#!/usr/bin/env python3
"""The kernel arguments bootc takes from an image's /usr/lib/bootc/kargs.d.

bootc applies them at `bootc install` and re-applies their difference at every
upgrade (bootc crates/lib/src/bootc_kargs.rs, get_kargs_in_root and
parse_kargs_toml). Live media built from the same image must boot with them
too, and tacklebox does not read kargs.d, so the ISO scripts pass them in the
recipe (scripts/lib/image-kargs.sh). This follows bootc's rules: `*.toml`
files in name order, each `kargs` list kept in order, a file with
`match-architectures` skipped unless it names the architecture, and any other
key an error.

Usage: bootc_kargs.py <kargs.d directory> <architecture, as uname -m prints it>
Prints one argument per line.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

KEYS = {"kargs", "match-architectures"}


def kargs(directory: Path, arch: str) -> list[str]:
    if not directory.is_dir():
        return []
    result: list[str] = []
    for path in sorted((p for p in directory.iterdir() if p.suffix == ".toml"), key=lambda p: p.name):
        try:
            config = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"{path.name}: {error}") from error
        unknown = set(config) - KEYS
        if unknown:
            raise ValueError(f"{path.name}: unknown key(s) {', '.join(sorted(unknown))}")
        entries = config.get("kargs")
        if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
            raise ValueError(f"{path.name}: kargs must be a list of strings")
        arches = config.get("match-architectures")
        if arches is not None and arch not in arches:
            continue
        for entry in entries:
            result.extend(entry.split())
    return result


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: bootc_kargs.py <kargs.d directory> <architecture>", file=sys.stderr)
        return 2
    try:
        for karg in kargs(Path(argv[1]), argv[2]):
            print(karg)
    except (OSError, ValueError) as error:
        print(f"bootc_kargs.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
