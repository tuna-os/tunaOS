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
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARE = REPO / "system_files/usr/share/tunaos"
BRANDING = REPO / "scripts/branding"
SETS = ("logos", "lettermarks", "fastfetch")
# importable module -> the pinned package in requirements-branding.txt
REQUIREMENTS = {"fontTools": "fonttools", "pyfiglet": "pyfiglet", "uharfbuzz": "uharfbuzz"}


def missing_requirements() -> list[str]:
    return sorted(package for module, package in REQUIREMENTS.items() if importlib.util.find_spec(module) is None)


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
    missing = missing_requirements()
    if missing:
        print(f"Artwork generation needs {', '.join(missing)}. Install the pinned set with:\n"
              f"  {Path(sys.executable).name} -m pip install -r requirements-branding.txt", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="tunaos-artwork-") as scratch:
        try:
            generate(Path(scratch))
        except subprocess.CalledProcessError as error:
            # A generator names its own problem on stderr (for example an emoji
            # with no drawing); nothing committed has been touched yet.
            print(f"{Path(error.cmd[1]).name} failed (see above); committed artwork is unchanged.", file=sys.stderr)
            return 1
        if args.write:
            # Copy every set next to its destination first; only then swap each in by
            # rename, so a copy that fails leaves the committed files untouched.
            staged = {}
            try:
                for name in SETS:
                    staged[name] = SHARE / f".{name}.new"
                    shutil.rmtree(staged[name], ignore_errors=True)
                    staged[name].mkdir(parents=True)
                    for fresh in (Path(scratch) / name).iterdir():
                        shutil.copyfile(fresh, staged[name] / fresh.name)
            except BaseException:
                for path in staged.values():
                    shutil.rmtree(path, ignore_errors=True)
                raise
            for name in SETS:
                old = SHARE / f".{name}.old"
                shutil.rmtree(old, ignore_errors=True)
                if (SHARE / name).exists():
                    (SHARE / name).rename(old)
                staged[name].rename(SHARE / name)
                shutil.rmtree(old, ignore_errors=True)
            print("Regenerated " + ", ".join(f"{SHARE.relative_to(REPO)}/{name}" for name in SETS))
            return 0
        problems = [p for name in SETS for p in differences(Path(scratch) / name, SHARE / name)]
    if problems:
        print("Artwork drifted from tunaos.toml:", *problems, sep="\n  ", file=sys.stderr)
        print("Run: python3 scripts/branding/check-artwork.py --write", file=sys.stderr)
        return 1
    print("Artwork matches tunaos.toml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
