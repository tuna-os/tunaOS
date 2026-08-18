"""W8 architecture honesty, hummingbird arm64 (#1755 option A).

The aarch64 rebuild repo began publishing on 2026-08-18
(hummingbird/20251124-aarch64 — it 404'd when #1755 was filed), but it is a
1358-package seed against x86_64's 8100: measured against its live
primary.xml, cosmic has 8 of its 22 manifest packages, gnome 5 of 52, with
no gnome-shell, no gdm, and no COSMIC compositor. An arm64 desktop leg
would install almost nothing under --skip-unavailable and publish the #858
shape — an image with no desktop — so the desktop flavors are pinned
amd64-only until per-desktop coverage exists, exactly like grouper:cosmic.

This test keeps the pin deliberate: whoever re-adds linux/arm64 to a
desktop flavor deletes that flavor from the pinned set below IN THE SAME
CHANGE, which is the reviewable claim that the aarch64 index now carries
that desktop's manifest set.
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

PINNED_AMD64_ONLY = {"gnome", "kde", "niri", "cosmic"}


def _hummingbird() -> dict:
    cfg = yaml.safe_load(
        (ROOT / ".github" / "build-config.yml").read_text(encoding="utf-8"))
    return next(v for v in cfg["variants"] if v["id"] == "hummingbird")


def test_desktop_flavors_are_amd64_only_until_the_aarch64_repo_converges():
    hb = _hummingbird()
    for flavor in hb["flavors"]:
        if flavor["id"] in PINNED_AMD64_ONLY:
            assert flavor.get("platforms") == ["linux/amd64"], (
                f"hummingbird:{flavor['id']} declares "
                f"{flavor.get('platforms', hb['platforms'])} — re-adding "
                f"arm64 requires measuring the desktop's manifest set "
                f"against the live aarch64 index and removing the flavor "
                f"from PINNED_AMD64_ONLY in the same change")


def test_base_keeps_both_arches():
    """base needs no rebuild repo and promotes on both arches — the pin is
    about desktop package coverage, not the variant."""
    hb = _hummingbird()
    base = next(f for f in hb["flavors"] if f["id"] == "base")
    assert base.get("platforms", hb["platforms"]) == [
        "linux/amd64", "linux/arm64"]
