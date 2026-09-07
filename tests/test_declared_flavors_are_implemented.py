"""A variant may not advertise a desktop it has no package set for.

`build_scripts/desktop/install-desktop.sh` routes hummingbird to the
`packages.hummingbird` section of `manifests/desktops/<flavor>.yaml` by
construction. A flavor with no such section has nothing to install, so its
image build cannot succeed -- and it does not fail quietly in isolation.

`build_artifacts_s2` takes `needs: build_stage2`, a matrix job over every
stage-2 flavor, so ONE failing leg skips every ISO in the stage
(tuna-os/tunaOS#2059). Measured on run 32786338463: hummingbird declared
gnome, kde, niri and cosmic; only gnome (52 packages) and cosmic (23) had a
`packages.hummingbird` section; kde and niri had none; and kde and niri were
exactly the two image builds that failed -- taking gnome's ISO down with them,
though gnome itself built, signed and manifested cleanly.

gnome is the only desktop with a passing installer-smoke cell anywhere in
docs/MATRIX-STATUS.md, so the flavors that were never implemented were
blocking the only one that demonstrably works.

This is deliberately about DECLARED vs IMPLEMENTED, not about which desktops
are desirable. Re-adding kde or niri is correct the moment either grows a
package section.
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def declared(variant: str) -> list[str]:
    config = yaml.safe_load((ROOT / ".github" / "build-config.yml").read_text())
    entry = next(v for v in config["variants"] if v["id"] == variant)
    return [f["id"] for f in entry["flavors"] if f.get("build_image")]


def implemented(variant: str, flavor: str) -> int:
    path = ROOT / "manifests" / "desktops" / f"{flavor}.yaml"
    if not path.exists():
        return 0
    manifest = yaml.safe_load(path.read_text()) or {}
    section = (manifest.get("packages") or {}).get(variant) or {}
    return len(section.get("packages") or [])


def test_every_declared_hummingbird_desktop_has_a_package_set() -> None:
    missing = {
        flavor: implemented("hummingbird", flavor)
        for flavor in declared("hummingbird")
        if flavor != "base" and implemented("hummingbird", flavor) == 0
    }
    assert not missing, (
        f"hummingbird declares {sorted(missing)} with build_image: true but "
        "manifests/desktops/<flavor>.yaml has no packages.hummingbird section "
        "for them. install-desktop.sh routes hummingbird to that section, so "
        "these cannot build -- and because build_artifacts_s2 needs the whole "
        "build_stage2 matrix, their failure skips every stage-2 ISO including "
        "gnome's (#2059)"
    )


def test_the_flavors_that_are_implemented_are_still_declared() -> None:
    """Guard the guard, in both directions.

    Deleting a flavor is a cheap way to make the assertion above pass, so pin
    that the implemented ones remain advertised -- otherwise 'no declared
    flavor lacks a manifest' could be satisfied by declaring nothing.
    """
    flavors = declared("hummingbird")
    for flavor in ("gnome", "cosmic"):
        assert implemented("hummingbird", flavor) > 0, (
            f"{flavor} lost its packages.hummingbird section"
        )
        assert flavor in flavors, (
            f"{flavor} has a hummingbird package set but is no longer declared"
        )
    assert "gnome" in flavors, "gnome is the only desktop with a passing installer-smoke cell"
