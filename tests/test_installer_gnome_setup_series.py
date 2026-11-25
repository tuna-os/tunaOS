"""The gnome-setup patch series stays applicable, ordered, and documented.

A missing patch, a gap in numbering, or a draft without a patch means the
medium builds the wrong Setup or nobody can send the series upstream.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "installer-medium" / "frontends" / "gnome-setup"
PATCHES = FRONTEND / "patches"
DRAFTS = FRONTEND / "upstream-drafts"


def _pins() -> dict[str, str]:
    values = {}
    for line in (FRONTEND / "PIN").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_pin_points_at_upstream_stf_setup() -> None:
    pins = _pins()
    assert re.fullmatch(r"[0-9a-f]{40}", pins["GNOME_SETUP_PIN"])
    assert pins["GNOME_SETUP_UPSTREAM"] == "https://gitlab.gnome.org/Teams/STF/setup.git"


def test_patch_series_is_contiguous_from_0001() -> None:
    files = sorted(p.name for p in PATCHES.glob("000*.patch"))
    assert len(files) >= 1
    assert [f[:4] for f in files] == [f"{n:04d}" for n in range(1, len(files) + 1)]


def test_every_patch_is_a_format_patch_mail() -> None:
    for patch in sorted(PATCHES.glob("000*.patch")):
        first = patch.read_text().splitlines()[0]
        assert re.fullmatch(r"From [0-9a-f]{40} .*", first), patch.name


def test_every_patch_has_an_upstream_draft_and_back() -> None:
    prefixes = {p.name[:4] for p in PATCHES.glob("000*.patch")}
    drafts = sorted(DRAFTS.glob("*.md"))
    assert drafts, "no upstream drafts"
    bodies = {d.name[:4]: d.read_text() for d in drafts}
    for prefix, body in bodies.items():
        assert f"patches/{prefix}-" in body, prefix
    for prefix in prefixes:
        assert any(f"patches/{prefix}-" in body for body in bodies.values()), prefix

def test_build_harness_is_wired() -> None:
    script = FRONTEND / "apply-and-build"
    assert script.stat().st_mode & 0o111, "apply-and-build is not executable"
    containerfile = (FRONTEND / "Containerfile").read_text()
    assert "apply-and-build" in containerfile
