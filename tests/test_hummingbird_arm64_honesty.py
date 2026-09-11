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


def test_cosmic_does_not_pin_an_arch_the_variant_does_not_offer():
    """COSMIC's own package set converged on aarch64 (2026-09-06) and the
    flavor still declares no platforms of its own, so it inherits whatever the
    variant offers. That is the honest shape: the reason arm64 is unavailable
    today is one layer below COSMIC, in the base, and this flavor should follow
    the variant back to arm64 automatically when the base can build there."""
    hb = _hummingbird()
    cosmic = next(f for f in hb["flavors"] if f["id"] == "cosmic")
    assert cosmic.get("platforms") is None, (
        "hummingbird:cosmic should inherit the variant's platforms — its own "
        "package set resolves on aarch64, so it must not carry an independent "
        "pin that would outlive the base's arm64 gap")


def test_the_variant_drops_arm64_while_its_base_cannot_resolve_xfsprogs():
    """The base stage's xfsprogs guard is mandatory and unsatisfiable on arm64.

    Measured against the live indexes on 2026-09-11 rather than inferred
    (repo.tunaos.org/hummingbird/20251124-$basearch/repodata, primary.xml):

        x86_64   13442 packages   xfsprogs: 1   malcontent: 2
        aarch64   7177 packages   xfsprogs: 0   malcontent: 0

    build_scripts/10-base-packages.sh exits 1 when xfsprogs is absent, by
    design (`bootc install to-disk` cannot format the root without it), so
    every hummingbird arm64 build died in the base stage — run 34545625709,
    both `base / linux-arm64` and `cosmic / linux-arm64`, after three attempts.

    Re-add "linux/arm64" here in the same change that measures xfsprogs present
    in the aarch64 snapshot. Removing this assertion without that measurement
    puts the nightly back to failing every arm64 leg.
    """
    hb = _hummingbird()
    assert hb["platforms"] == ["linux/amd64"]
    base = next(f for f in hb["flavors"] if f["id"] == "base")
    assert base.get("platforms") is None, (
        "base should inherit the variant's platforms, so that restoring arm64 "
        "is a single edit in one reviewable place")
