"""guppy's ostree must be built with libarchive, or no OCI flatpak installs.

flatpak imports each layer of an `oci+https` remote through ostree's archive
importer. The tuna-os remote (https://tunaos.org/flatpak/tuna-os.flatpakrepo)
is `Url=oci+https://tunaos.org/flatpak`, and Gentoo's dev-util/ostree leaves
the `archive` USE flag off by default. The guppy:xfce live overlay died on it
(tunaOS live-overlay run 43435829108):

    Error: Failed to install org.tunaos.InstallerXfce: This version of ostree
    is not compiled with libarchive support

Falsification: delete the `dev-util/ostree archive` package.use line or the
`--binpkg-respect-use=y` on the ostree emerge in Containerfile.gentoo; this
test fails. The build-time ldd guard is what fails if the flag stops taking.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINERFILE = (ROOT / "Containerfile.gentoo").read_text()


def _ostree_run() -> str:
    for block in re.split(r"\n(?=RUN |FROM )", CONTAINERFILE):
        if block.startswith("RUN emerge") and "dev-util/ostree" in block:
            return block
    raise AssertionError("no RUN in Containerfile.gentoo emerges dev-util/ostree")


def test_ostree_is_emerged_with_the_archive_use_flag():
    use = 'echo "dev-util/ostree archive" > /etc/portage/package.use/ostree'
    assert use in CONTAINERFILE
    builder = CONTAINERFILE.index("FROM base AS builder")
    assert builder < CONTAINERFILE.index(use) < CONTAINERFILE.index(_ostree_run())


def test_a_binhost_build_without_the_flag_cannot_satisfy_it():
    # The base stage sets --binpkg-respect-use=n, under which a published
    # ostree without libarchive would be taken as-is.
    emerge = next(line for line in _ostree_run().splitlines() if "emerge " in line)
    assert "--binpkg-respect-use=y" in emerge


def test_the_build_fails_when_libostree_lacks_libarchive():
    run = _ostree_run()
    assert re.search(r"ldd /usr/lib64/libostree-1\.so\.1 \| grep -q libarchive", run)
    assert "exit 1" in run
