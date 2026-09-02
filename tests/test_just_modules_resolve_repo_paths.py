"""A recipe moved into just/ must not carry a relative repo path with it.

Recipes in the root `Justfile` can say `scripts/lib/common.sh` and it
resolves, because that is where the file is. When #508's modularisation moves
a recipe into `just/*.just`, the *text* is unchanged but the path no longer
resolves the same way -- shebang recipes execute from a temp file, and the
relative path is interpreted against a working directory the recipe never
declared.

The failure is invisible in review, because the moved line is byte-identical
to the line that worked. It surfaces only at runtime:

    /tmp/justDGc4ap/qcow2: line 124: scripts/lib/common.sh: No such file or directory
    ERROR: could not probe ghcr.io/tuna-os/marlin:gnome-testing for its bootc backend

On the 2026-08-17 nightly that took out every `Gate` job on marlin (4) and
grouper (2). The boot gate is what proves an image actually reaches a
graphical session, so losing it silently removes the strongest evidence the
matrix has that a cell really works.

`{{ justfile_directory() }}` anchors to the root justfile's directory
regardless of how or from where the recipe is invoked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "just"

# A repo-relative path used as a command or sourced file: `. scripts/x`,
# `source scripts/x`, `python3 scripts/x`, `bash scripts/x`. Anchored ones
# ({{ justfile_directory() }}/scripts/... or /abs/scripts/...) are fine, as
# are strings inside a longer path such as `docs/scripts/`.
BARE_RELATIVE = re.compile(
    r"(?:^|[^/\w.{-])(?:\.|source|bash|sh|python3)\s+(scripts/[\w./-]+)"
)

MODULES = sorted(MODULE_DIR.glob("*.just")) if MODULE_DIR.is_dir() else []


def test_there_are_modules_to_check():
    """Guard against this whole file silently passing if just/ moves."""
    assert MODULES, f"no just modules found under {MODULE_DIR}"


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_module_scripts_are_anchored_to_the_justfile_directory(module):
    offenders = []
    for lineno, line in enumerate(module.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        for match in BARE_RELATIVE.finditer(line):
            offenders.append(f"{module.name}:{lineno}: {match.group(1)}")

    assert not offenders, (
        "repo-relative script path in a just module — it resolved in the root "
        "Justfile and will not resolve here. Prefix with "
        "'{{ justfile_directory() }}/':\n  " + "\n  ".join(offenders)
    )


def test_the_qcow2_probe_is_anchored():
    """The specific line that cost marlin and grouper their boot gates.

    Named explicitly rather than left to the sweep above, so that if someone
    rewrites the pattern-matching this particular regression keeps a test of
    its own.
    """
    body = (MODULE_DIR / "qcow2-build.just").read_text(encoding="utf-8")
    assert "{{ justfile_directory() }}/scripts/lib/common.sh" in body
    assert ". scripts/lib/common.sh" not in body


SHEBANG = "#!/usr/bin/env bash"
CD_ANCHOR = "cd {{ justfile_directory() }}"


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_module_shebang_recipes_start_at_the_repo_root(module):
    """Every bash recipe in an imported module must cd to the repo root first.

    The just version decides an imported recipe's working directory: 1.21.0
    (what Ubuntu 24.04's apt installs on the Gate runners) runs it from the
    directory of the imported file — just/ — while 1.25+ runs it from the root
    justfile's directory.  Measured, not assumed: marlin's Gate run
    31999186436 rendered $(pwd)/system_files/... as
    tunaOS/just/system_files/... and bootc failed the statfs, one step after
    the scripts/lib/common.sh fix from the same import move (#1586, #1811).

    An explicit `cd {{ justfile_directory() }}` is version-proof: the function
    is evaluated by just itself and returns the root justfile's directory on
    every version (verified on 1.21.0, 1.42.4 and 1.55.1).  It also puts
    recipe outputs (marlin.qcow2) back at the repo root, where the workflow's
    `find . -maxdepth 1 -name '*.qcow2'` expects them.
    """
    lines = module.read_text(encoding="utf-8").splitlines()
    offenders = []
    for lineno, line in enumerate(lines, 1):
        if line.strip() != SHEBANG:
            continue
        # The cd must appear within the next two lines (a `set` line may
        # come first so an unwritable root fails loudly under -e).
        window = [l.strip() for l in lines[lineno:lineno + 2]]
        if not any(CD_ANCHOR in l for l in window):
            offenders.append(f"{module.name}:{lineno}")

    assert not offenders, (
        "bash recipe in a just module without an explicit repo-root cd — on "
        "the Gate runners' just 1.21.0 it runs from just/ and every "
        "repo-relative path or output lands in the wrong place:\n  "
        + "\n  ".join(offenders)
    )


def test_no_pwd_anchored_repo_paths_in_modules():
    """$(pwd) said repo root in the root Justfile; in a module it lies."""
    for module in MODULES:
        for lineno, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), 1
        ):
            for token in ("$(pwd)/system_files", "$(pwd)/scripts",
                          "${PWD}/system_files", "${PWD}/scripts"):
                assert token not in line, (
                    f"{module.name}:{lineno} anchors a repo path to the "
                    "working directory; use '{{ justfile_directory() }}/'"
                )
