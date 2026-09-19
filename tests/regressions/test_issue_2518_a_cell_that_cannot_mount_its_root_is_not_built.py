"""tunaOS#2518: `*-nvidia-hwe` stays unbuilt on EL10 until it can boot.

The three EL10 variants — albacore, yellowfin, skipjack — each declared
`gnome-nvidia-hwe`, and all three built it, signed it, passed its desktop
contract and then booted into an emergency shell:

    mount: /sysroot: unknown filesystem type 'xfs'
    Dependency failed for ostree-prepare-root.service - OSTree Prepare OS/.

Albacore run 34745445506 reached this at 10.6s and yellowfin run 34738897386
at 10.3s, on roots that really are XFS.

`-hwe` selects the coreos-stable akmods bundle, so the kernel swap installs
Fedora 43's kernel into an EL10 userspace whose dracut is dracut-107-8.el10.
That dracut leaves XFS out of the initramfs without reporting anything. The
non-HWE NVIDIA cells take 6.12.0-266.el10 from the centos-10 bundle and boot,
which is why only this combination is red. There is no EL10 HWE akmods bundle
to switch to. Naming the filesystems in the dracut rebuild was tried and
reverted in tunaOS#2517: `--filesystems` is strict, EL10 ships no Btrfs, and it
broke every EL10 `*-nvidia` cell to repair this one.

The flavor remains declared but is not built. The cell stays off until someone
changes it deliberately, and the evidence for why stays with it.

Falsification: structural — setting any affected flavor's `build_image` back
to true, deleting its declaration or rationale, or bypassing the ISO group's
buildable-flavor filter makes these tests fail.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".github/build-config.yml"
EL10_FAMILY = ("albacore", "yellowfin", "skipjack")


def _variants():
    return {v["id"]: v for v in yaml.safe_load(CONFIG.read_text())["variants"]}


def test_every_el10_variant_still_declares_the_flavor():
    # Declared, not deleted: the block carries the reason and the route back.
    variants = _variants()
    for variant in EL10_FAMILY:
        ids = [flavor["id"] for flavor in variants[variant]["flavors"]]
        assert "gnome-nvidia-hwe" in ids


def test_none_of_the_el10_variants_build_the_flavor():
    variants = _variants()
    for variant in EL10_FAMILY:
        flavor = next(
            flavor
            for flavor in variants[variant]["flavors"]
            if flavor["id"] == "gnome-nvidia-hwe"
        )
        assert not flavor.get("build_image"), (
            f"{variant}:gnome-nvidia-hwe is building again. It boots to an "
            "emergency shell on 'unknown filesystem type xfs' (tunaOS#2518); "
            "turn it on only with a Gate that mounts /sysroot."
        )


def test_the_config_blocks_say_why_the_flavor_is_off():
    # A bare `build_image: false` is indistinguishable from an oversight.
    text = CONFIG.read_text()
    assert "unknown filesystem type 'xfs'" in text
    assert "tunaOS#2518" in text


def test_the_matrix_no_longer_counts_the_cells():
    built = {
        f"{variant['id']}:{flavor['id']}"
        for variant in _variants().values()
        for flavor in variant["flavors"]
        if flavor.get("build_image")
    }
    for variant in EL10_FAMILY:
        assert f"{variant}:gnome-nvidia-hwe" not in built


def test_the_iso_group_drops_the_cells_on_its_own():
    # The group is intersected with build_image:true, so its old name is not a
    # dangling reference.
    script = (ROOT / "scripts/build-iso-group.sh").read_text()
    assert "select(.build_image == true)" in script
    assert "# Intersect, preserving group/offline order." in script
