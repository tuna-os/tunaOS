"""W8 architecture honesty, hummingbird arm64 (#1755 option A).

Desktop flavors stay amd64-only until their complete package source exists
on aarch64. The Hummingbird package factory has now converged for COSMIC, but
GNOME still comes from the amd64-only utah-packages OCI repository. Keep that
remaining pin explicit so adding arm64 is a reviewable availability claim.
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

PINNED_AMD64_ONLY = {"gnome"}


def _hummingbird() -> dict:
    cfg = yaml.safe_load(
        (ROOT / ".github" / "build-config.yml").read_text(encoding="utf-8"))
    return next(v for v in cfg["variants"] if v["id"] == "hummingbird")


def test_desktop_flavors_without_aarch64_package_sources_are_amd64_only():
    hb = _hummingbird()
    for flavor in hb["flavors"]:
        if flavor["id"] in PINNED_AMD64_ONLY:
            assert flavor.get("platforms") == ["linux/amd64"], (
                f"hummingbird:{flavor['id']} declares "
                f"{flavor.get('platforms', hb['platforms'])} — re-adding "
                f"arm64 requires measuring the desktop's manifest set "
                f"against the live aarch64 index and removing the flavor "
                f"from PINNED_AMD64_ONLY in the same change")


def test_cosmic_uses_both_converged_package_repositories():
    hb = _hummingbird()
    cosmic = next(f for f in hb["flavors"] if f["id"] == "cosmic")
    assert cosmic.get("platforms", hb["platforms"]) == [
        "linux/amd64", "linux/arm64"]


def test_base_keeps_both_arches():
    """base needs no rebuild repo and promotes on both arches — the pin is
    about desktop package coverage, not the variant."""
    hb = _hummingbird()
    base = next(f for f in hb["flavors"] if f["id"] == "base")
    assert base.get("platforms", hb["platforms"]) == [
        "linux/amd64", "linux/arm64"]
