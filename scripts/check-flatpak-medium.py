#!/usr/bin/env python3
"""Assert a live medium bakes exactly the declared Flatpak set (tunaOS#4907).

The declared set is build_scripts/desktop/flatpak-preinstall.tsv, which is
generated from [flatpak_preinstall] in tunaos.toml (scripts/lib/flatpak_preinstall.py).
The baked set is read from a preinstall.d directory, or from a list of app IDs.

    check-flatpak-medium.py --desktop gnome --preinstall-dir <root>/usr/share/flatpak/preinstall.d
    check-flatpak-medium.py --desktop kde --app io.github.kolunmi.Bazaar --app org.mozilla.firefox

Exit 0 when equal. Exit 1 with a diff naming each missing, extra and
wrong-branch app. Exit 2 on bad input. Runtime sections (IsRuntime=true) are
not apps and are ignored: the medium bakes the runtimes the apps pull in.
"""

from __future__ import annotations

import argparse
import configparser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "build_scripts/desktop/flatpak-preinstall.tsv"
SECTION_PREFIX = "Flatpak Preinstall "


class InputError(ValueError):
    """The policy or the baked set cannot be read."""


def expected_set(policy_path: Path, desktop: str) -> dict[str, str]:
    """Return {app id: branch} for a desktop: the '*' rows plus its own rows."""
    try:
        text = policy_path.read_text()
    except OSError as err:
        raise InputError(f"cannot read policy {policy_path}: {err}") from err
    apps: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise InputError(f"{policy_path}:{number}: expected scope, app ID, branch")
        scope, app, branch = fields
        if scope in ("*", desktop):
            apps[app] = branch
    return apps


def baked_from_dir(directory: Path) -> dict[str, str]:
    """Return {app id: branch} from every *.preinstall file in a directory."""
    if not directory.is_dir():
        raise InputError(f"not a directory: {directory}")
    apps: dict[str, str] = {}
    for path in sorted(directory.glob("*.preinstall")):
        parser = configparser.RawConfigParser(strict=False)
        parser.optionxform = str
        try:
            parser.read_string(path.read_text())
        except (OSError, configparser.Error) as err:
            raise InputError(f"cannot parse {path}: {err}") from err
        for section in parser.sections():
            if not section.startswith(SECTION_PREFIX):
                continue
            if parser.get(section, "IsRuntime", fallback="false").strip().lower() == "true":
                continue
            apps[section[len(SECTION_PREFIX):].strip()] = parser.get(section, "Branch", fallback="stable").strip()
    return apps


def baked_from_ids(ids: list[str]) -> dict[str, str]:
    """Return {app id: branch} from IDs; `id//branch` names a branch, else stable."""
    apps: dict[str, str] = {}
    for item in ids:
        app, _, branch = item.partition("//")
        apps[app] = branch or "stable"
    return apps


def diff(expected: dict[str, str], baked: dict[str, str]) -> list[str]:
    """Return one line per difference; empty means the sets are equal."""
    lines = [f"missing from the medium: {app} ({expected[app]})" for app in sorted(expected.keys() - baked.keys())]
    lines += [f"not declared in tunaos.toml: {app} ({baked[app]})" for app in sorted(baked.keys() - expected.keys())]
    lines += [
        f"wrong branch: {app} declared {expected[app]}, baked {baked[app]}"
        for app in sorted(expected.keys() & baked.keys())
        if expected[app] != baked[app]
    ]
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--desktop", required=True, help="logical desktop id, such as gnome or kde")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--preinstall-dir", type=Path, help="the medium's flatpak preinstall.d directory")
    source.add_argument("--app", action="append", help="a baked app ID (repeatable)")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY, help="the generated flatpak-preinstall.tsv")
    args = parser.parse_args(argv)
    try:
        expected = expected_set(args.policy, args.desktop)
        baked = baked_from_dir(args.preinstall_dir) if args.preinstall_dir else baked_from_ids(args.app)
    except InputError as err:
        print(f"check-flatpak-medium: {err}", file=sys.stderr)
        return 2
    problems = diff(expected, baked)
    if problems:
        print(f"check-flatpak-medium: the {args.desktop} medium differs from {args.policy.name}:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"check-flatpak-medium: {args.desktop} medium matches ({len(expected)} apps)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
