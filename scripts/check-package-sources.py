#!/usr/bin/env python3
"""Reject new package-source declarations outside system repos and Tideforge."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contracts.sources import ALLOWED_REPO_HOSTS, FORBIDDEN_KEYS, classify_policy, violations


def changed_files(base: str) -> list[Path]:
    output = subprocess.check_output(["git", "diff", "--name-only", f"{base}...HEAD"], text=True)
    return [Path(line) for line in output.splitlines() if line]


def at_revision(base: str, path: Path) -> object | None:
    """The manifest as it was at `base`, or None if it did not exist there.

    None and an empty document are different answers and must stay that way:
    a manifest added by this diff has no baseline, so every source in it is
    new and all of them are reported.
    """
    try:
        blob = subprocess.check_output(
            ["git", "show", f"{base}:{path.as_posix()}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None
    try:
        return yaml.safe_load(blob) or {}
    except yaml.YAMLError:
        # An unparseable baseline cannot exonerate anything; fall back to
        # reporting the whole file rather than silently passing it.
        return None


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
        found = violations(document)
        # Report what this change ADDED, not everything the file happens to
        # contain. PACKAGE-SOURCING.md §Enforcement is explicit about which
        # of the two this gate is: it "blocks new manifest changes that add
        # COPR, PPA, OBS, AUR, or an unapproved repository URL", and
        # "existing legacy declarations remain migration inventory until
        # their package is available in Tideforge or a documented allowlist
        # exception is approved". This module's own docstring says "new"
        # too. Neither was implemented: "new" was approximated as "present
        # in a file the diff touched", so ANY edit to a manifest carrying a
        # grandfathered source failed the gate.
        #
        # Measured: adding an unrelated `eln:` section to
        # manifests/desktops/gnome.yaml failed CI on
        # `packages.el10.copr` — the GNOME 50 EL10 backport, which has been
        # on main since before this script existed, carries its policy
        # exception in a comment beside it, and was NOT touched by that
        # diff. The gate could not tell "you added a COPR" from "you edited
        # a file that has one", which is the distinction it exists to make.
        #
        # Diffing parsed documents rather than raw lines is deliberate:
        # reformatting, re-indenting or moving an existing block must not
        # read as an addition, and a line-based diff would say it does.
        if args.base:
            baseline = at_revision(args.base, path)
            if baseline is not None:
                found = classify_policy(document, baseline)["forbiddenNew"]
        errors.extend(f"{path}: {error}" for error in found)
    if errors:
        print("Package source policy violations:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        print("Build missing packages in Tideforge or use the base system repository; see PACKAGE-SOURCING.md.", file=sys.stderr)
        return 1
    print(f"Package source policy OK ({len(manifests)} changed manifest(s) checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
