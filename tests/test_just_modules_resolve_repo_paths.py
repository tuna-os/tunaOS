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
