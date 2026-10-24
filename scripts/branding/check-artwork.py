#!/usr/bin/env python3
"""Regenerate the artwork that is reproducible from tunaos.toml and compare it.

    scripts/branding/check-artwork.py           # fail on any difference
    scripts/branding/check-artwork.py --write   # regenerate the committed files

Covers the marks (make-logos.py), lettermarks (make-lettermarks.py) and
fastfetch letters (make-fastfetch-logos.py). They follow a variant's emoji,
name and accent, so a fork that edits those in tunaos.toml regenerates these
files instead of keeping TunaOS artwork. Wallpapers and boot splashes are
drawn, not derived, and are not covered here.

Needs pinned requirements-branding.txt. The generator uses the vendored
Baloo 2 source under scripts/branding/assets and never needs network access.
"""
from __future__ import annotations

import argparse
import filecmp
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARE = REPO / "system_files/usr/share/tunaos"
BRANDING = REPO / "scripts/branding"
SETS = ("logos", "lettermarks", "fastfetch")


def generate(root: Path) -> None:
    """Run the generators in dependency order: lettermarks embed the marks."""
    run = lambda *args: subprocess.run([sys.executable, *map(str, args)], check=True, stdout=subprocess.DEVNULL)
    run(BRANDING / "make-logos.py", "--output", root / "logos")
    run(BRANDING / "make-lettermarks.py", "--output", root / "lettermarks", "--logos", root / "logos")
    run(BRANDING / "make-fastfetch-logos.py", "--output", root / "fastfetch")


def differences(generated: Path, committed: Path) -> list[str]:
    names = {p.name for p in generated.iterdir()} | {p.name for p in committed.iterdir()}
    problems = []
    for name in sorted(names):
        fresh, kept = generated / name, committed / name
        where = f"{committed.relative_to(REPO)}/{name}"
        if not kept.exists():
            problems.append(f"{where}: missing (generated from tunaos.toml, not committed)")
        elif not fresh.exists():
            problems.append(f"{where}: stale (no variant in tunaos.toml produces it)")
        elif not filecmp.cmp(fresh, kept, shallow=False):
            problems.append(f"{where}: differs")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="regenerate the committed files")
    args = parser.parse_args()
    if args.write:
        for name in SETS:
            for stale in (SHARE / name).glob("*"):
                stale.unlink()
        generate(SHARE)
        print("Regenerated " + ", ".join(f"{SHARE.relative_to(REPO)}/{name}" for name in SETS))
        return 0
    with tempfile.TemporaryDirectory(prefix="tunaos-artwork-") as scratch:
        generate(Path(scratch))
        problems = [p for name in SETS for p in differences(Path(scratch) / name, SHARE / name)]
    if problems:
        print("Artwork drifted from tunaos.toml:", *problems, sep="\n  ", file=sys.stderr)
        print("Run: python3 scripts/branding/check-artwork.py --write", file=sys.stderr)
        return 1
    print("Artwork matches tunaos.toml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
