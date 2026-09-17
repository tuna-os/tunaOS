"""`*-nvidia-hwe` stays undeclared on the EL10 family until it can boot.

The three EL10 variants — albacore, yellowfin, skipjack — each declared
`gnome-nvidia-hwe`, and all three built it, signed it, passed its desktop
contract and then booted into an emergency shell:

    mount: /sysroot: unknown filesystem type 'xfs'
    Dependency failed for ostree-prepare-root.service - OSTree Prepare OS/.

albacore run 34745445506 at 10.6s, yellowfin run 34738897386 at 10.3s, on a
root that really is XFS.

`-hwe` selects the coreos-stable akmods bundle, so the kernel swap installs
Fedora 43's kernel into an EL10 userspace whose dracut is dracut-107-8.el10.
That dracut leaves xfs out of the initramfs without reporting anything. The
non-HWE nvidia cells take 6.12.0-266.el10 from the centos-10 bundle and boot,
which is why only this combination is red. There is no EL10 HWE akmods bundle
to switch to. Naming the filesystems in the dracut rebuild was tried and
reverted in tunaOS#2517: `--filesystems` is strict, EL10 ships no btrfs, and it
broke every EL10 *-nvidia cell to repair this one.

So the flavor is declared but not built, the way tunaOS#2492 handled
sailfin:gnome-asahi. These tests hold that state: the cell stays off until
someone changes it deliberately, and the evidence for why stays with it.

tunaOS#2518 tracks getting it back.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github/build-config.yml"
EL10_FAMILY = ("albacore", "yellowfin", "skipjack")


def _variants():
    return {v["id"]: v for v in yaml.safe_load(CONFIG.read_text())["variants"]}


class TheFlavorIsDeclaredButNotBuilt(unittest.TestCase):
    def setUp(self):
        self.variants = _variants()

    def test_every_el10_variant_still_declares_it(self):
        # Declared, not deleted: the block carries the reason and the route
        # back. A silent deletion loses both.
        for variant in EL10_FAMILY:
            with self.subTest(variant=variant):
                ids = [f["id"] for f in self.variants[variant]["flavors"]]
                self.assertIn("gnome-nvidia-hwe", ids)

    def test_none_of_them_build_it(self):
        for variant in EL10_FAMILY:
            with self.subTest(variant=variant):
                flavor = next(f for f in self.variants[variant]["flavors"]
                              if f["id"] == "gnome-nvidia-hwe")
                self.assertFalse(
                    flavor.get("build_image"),
                    f"{variant}:gnome-nvidia-hwe is building again. It boots to "
                    "an emergency shell on 'unknown filesystem type xfs' "
                    "(tunaOS#2518); turn it on only with a Gate that mounts "
                    "/sysroot.")

    def test_the_block_says_why(self):
        # A bare `build_image: false` is indistinguishable from an oversight.
        # tunaOS#2492 set the precedent that the reason lives beside the flag.
        text = CONFIG.read_text()
        self.assertIn("unknown filesystem type 'xfs'", text)
        self.assertIn("tunaOS#2518", text)


class TheCellsAreGoneFromTheDenominator(unittest.TestCase):
    def test_the_matrix_no_longer_counts_them(self):
        built = {
            f"{v['id']}:{f['id']}"
            for v in _variants().values() for f in v["flavors"]
            if f.get("build_image")
        }
        for variant in EL10_FAMILY:
            with self.subTest(variant=variant):
                self.assertNotIn(f"{variant}:gnome-nvidia-hwe", built)

    def test_the_iso_group_drops_it_on_its_own(self):
        # scripts/build-iso-group.sh intersects each group's flavors with the
        # variant's build_image:true set, so the group listing it is not a
        # dangling reference. Verified in the script, not just its comment.
        script = (ROOT / "scripts/build-iso-group.sh").read_text()
        self.assertIn('select(.build_image == true)', script)
        self.assertIn("# Intersect, preserving group/offline order.", script)


if __name__ == "__main__":
    unittest.main()
