"""W8 architecture honesty, hummingbird arm64 (#1755 option A).

Desktop flavors stay amd64-only until their complete package sources exist on
aarch64. GNOME and COSMIC both consume the amd64-only utah-packages OCI
repository, so each flavor keeps an explicit pin independent of the current
base-level arm64 gap.
"""
from __future__ import annotations

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "tunaos_config_under_test", ROOT / "scripts" / "lib" / "tunaos_config.py")
tunaos_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tunaos_config)

PINNED_AMD64_ONLY = {"gnome", "cosmic"}


def _hummingbird() -> dict:
    cfg = tunaos_config.matrix(tunaos_config.load(ROOT / "tunaos.toml"))
    return next(v for v in cfg["variants"] if v["id"] == "hummingbird")

def test_desktop_flavors_without_aarch64_package_sources_are_amd64_only():
    hb = _hummingbird()
    for flavor in hb["flavors"]:
        if flavor["id"] in PINNED_AMD64_ONLY:
            platforms = flavor.get("platforms")
            assert platforms == ["linux/amd64"], (
                f"hummingbird:{flavor['id']} declares "
                f"{platforms} — re-adding arm64 requires measuring the "
                f"flavor's manifest set against the live aarch64 index and "
                f"removing the flavor from PINNED_AMD64_ONLY in the same change")




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
