"""guppy:kde must name sddm by the atom the Gentoo tree currently ships.

Build Guppy run 43560616230 (flavor=kde, 2026-11-14) died in the desktop stage:
`emerge: there are no ebuilds to satisfy "x11-misc/sddm".` The ebuild moved to
gui-apps/sddm (0.21.0_p20260819-r1, stable on amd64, packages.gentoo.org). The
last published guppy:kde (2026-10-20) predates the move, which is why nothing
broke until the image was rebuilt. emerge resolves the explicit argument list
before anything else, so one stale atom fails the whole desktop stage and the
live overlay for guppy:kde cannot be built from it.

Falsification: put `x11-misc/sddm` back in [desktops.kde.packages.emerge] and
this test fails.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def kde_emerge_atoms() -> list[str]:
    config = tomllib.loads((ROOT / "tunaos.toml").read_text())
    return config["desktops"]["kde"]["packages"]["emerge"]["required"]


def test_kde_emerge_list_uses_the_current_sddm_atom():
    atoms = kde_emerge_atoms()
    assert "gui-apps/sddm" in atoms
    assert "x11-misc/sddm" not in atoms
