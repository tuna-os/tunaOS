#!/usr/bin/env python3
"""The nvidia initramfs must carry the root filesystem's driver.

The `*-nvidia-hwe` cells on the EL10 family — albacore, yellowfin and
skipjack, the only three variants that declare the flavor — build, sign and
pass their desktop contract, then boot into an emergency shell:

    mount[597]: mount: /sysroot: unknown filesystem type 'xfs'.
    Failed to mount sysroot.mount - /sysroot.
    Dependency failed for ostree-prepare-root.service - OSTree Prepare OS/.

Identical on albacore run 34745445506 and yellowfin run 34738897386, on a root
that really is XFS.

It is the fc43-kernel-on-EL10 split that tunaos#1561 documents, one module
further on. `-hwe` selects the coreos-stable akmods bundle, so the kernel swap
installs kernel 7.1.8-100.fc43 into an EL10 userspace whose dracut is
dracut-107-8.el10_2. The non-HWE nvidia cells take 6.12.0-266.el10 from the
centos-10 bundle and boot, which is why only the -hwe combination is red.

Under `--no-hostonly` there is no fstab to read, so the filesystem set is
inferred — correctly for the kernel dracut shipped beside, not for the Fedora
one. The failure is silent: that dracut run reports no error and never mentions
xfs at all. So the filesystems are named explicitly, and this test holds that.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/overlay/overrides/nvidia/20-nvidia.sh"

# Every root filesystem the matrix actually installs onto: XFS on the EL10
# family, btrfs on the Fedora ones, ext4 where neither, vfat for the ESP.
REQUIRED = ("xfs", "ext4", "btrfs")


def _dracut_command() -> str:
    """The rebuild command, joined across any line continuations.

    Joined deliberately: a matcher that greps one line passes against a command
    split over three, which is how two earlier tests in this suite came to
    accept the very code they were written to reject.
    """
    text = SCRIPT.read_text().replace("\\\n", " ")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("/usr/bin/dracut"):
            return " ".join(stripped.split())
    raise AssertionError(f"no dracut rebuild found in {SCRIPT}")


class TheRebuildNamesItsFilesystems(unittest.TestCase):
    def setUp(self):
        self.command = _dracut_command()

    def test_the_filesystems_flag_is_present(self):
        self.assertIn("--filesystems", self.command,
                      "dracut is back to inferring the filesystem set; the EL10 "
                      "nvidia-hwe cells boot to an emergency shell when it "
                      "infers wrong, and it does so without an error")

    def test_every_root_filesystem_the_matrix_uses_is_named(self):
        match = re.search(r'--filesystems\s+"([^"]+)"', self.command)
        self.assertIsNotNone(match, f"--filesystems takes a quoted list: {self.command}")
        named = set(match.group(1).split())
        for fs in REQUIRED:
            with self.subTest(fs=fs):
                self.assertIn(fs, named)

    def test_it_still_rebuilds_for_the_swapped_kernel(self):
        # The flag must not have displaced --kver. An initramfs built for the
        # wrong kernel is the failure this cell already had once.
        self.assertIn('--kver "$QUALIFIED_KERNEL"', self.command)

    def test_it_is_still_a_generic_initramfs(self):
        # --no-hostonly is why naming the filesystems is needed at all; if it
        # ever goes, this test should be revisited rather than silently kept.
        self.assertIn("--no-hostonly", self.command)


class TheCellsThisProtectsStillExist(unittest.TestCase):
    """Vacuity guard (tunaOS#1730). The tests above would pass just as well if
    no variant declared an nvidia-hwe flavor at all — at which point they guard
    nothing and should be deleted rather than left looking like coverage."""

    def test_some_variant_still_declares_an_nvidia_hwe_cell(self):
        import yaml
        config = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
        declared = [
            f"{v['id']}:{f['id']}"
            for v in config["variants"] for f in v["flavors"]
            if f["id"].endswith("nvidia-hwe") and f.get("build_image")
        ]
        self.assertTrue(declared,
                        "no nvidia-hwe cell is built any more; this file has "
                        "nothing left to protect")


if __name__ == "__main__":
    unittest.main()
