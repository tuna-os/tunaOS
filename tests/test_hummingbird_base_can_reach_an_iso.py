"""The hummingbird base must ask for flatpak, or nothing downstream can work.

Building the `flatpak` PACKAGE is not enough. Something has to install it into
the image, and hummingbird takes its own branch of build_scripts/10-base-packages.sh
whose list is separate from the fedora and el10 ones -- the `flatpak` entries in
those branches never applied to it.

Why it matters three steps later. live-iso/common/src/customize-live.sh
pre-installs the installer app and exits 1 when flatpak cannot be made present:

    ERROR: flatpak not installed and could not be installed;
           cannot pre-install ${INSTALLER_APP}

scripts/build-iso-tacklebox.sh passes that same script as the ISO recipe's
live_customize step, and gnome's INSTALLER_APP is org.bootcinstaller.Installer
-- a Flatpak. So one missing package takes out the live-overlay build, the CI
ISO build, and the installer a user would click.

customize-live.sh's ensure_flatpak() fallback rescues bases that merely omit
the package from their image (guppy, grouper, bonito-rawhide, whose distros
all package it). It cannot rescue hummingbird: measured 2026-08-25, flatpak is
absent from BOTH public-hummingbird (3509 binary names) and our rebuild
snapshot (7986). It is layer-07 of the build order.

This pins the ask, not the outcome -- the package is not published yet, so the
image legitimately does not have it. What it prevents is the ask being dropped
and the gap resurfacing two stages later as something else, which is exactly
what xfsprogs did in run 32144269992.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts" / "10-base-packages.sh"


def hummingbird_branch() -> str:
    """Only the IS_HUMMINGBIRD branch, so the fedora/el10 lists cannot
    accidentally satisfy an assertion about hummingbird's."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("if [[ $IS_HUMMINGBIRD == true ]]")
    end = text.index("elif [[ $IS_FEDORA == true ]]", start)
    return text[start:end]


def test_the_branch_is_still_findable() -> None:
    """Guard the guard: a refactor that renames the branch must fail loudly
    here rather than leaving every assertion below vacuously true."""
    branch = hummingbird_branch()
    assert "--skip-unavailable" in branch
    assert "xfsprogs" in branch, "the branch no longer looks like the one measured"


def test_hummingbird_asks_for_flatpak() -> None:
    branch = hummingbird_branch()
    install = branch[branch.index("dnf -y install"):]
    install = install[:install.index("|| true")]
    packages = {line.strip().rstrip("\\").strip() for line in install.splitlines()}
    assert "flatpak" in packages, (
        "the hummingbird base does not install flatpak, so once the package "
        "is published the image still will not carry it -- and without it "
        "customize-live.sh exits 1, no overlay or ISO can be built, and there "
        "is no installer app to launch"
    )


def test_a_missing_flatpak_is_not_silent() -> None:
    """--skip-unavailable drops a missing package without a word. That is what
    made the xfsprogs fix look 'in place' while the Gate died at mkfs.xfs two
    stages later, and the same silence would hide this one until an ISO build
    failed for reasons that look unrelated."""
    branch = hummingbird_branch()
    assert re.search(r"rpm -q flatpak", branch), (
        "nothing checks whether flatpak actually installed; a silent miss is "
        "how the xfsprogs gap survived a fix"
    )
    assert "#1397" in branch, (
        "the check should point at the issue that explains the consequence, "
        "so whoever reads the warning does not have to rediscover it"
    )
