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


def dnf_install_blocks(branch: str) -> list[str]:
    """Every `dnf -y install ... || true` transaction in the branch, each as
    its own string. flatpak moved into its own transaction (tuna-os/
    tunaOS#1734) so a dependency conflict in ITS resolution can no longer
    fail the xfsprogs transaction batched alongside it -- tests that care
    about one transaction's contents must not assume there is only one."""
    blocks = []
    pos = 0
    while True:
        start = branch.find("dnf -y install", pos)
        if start == -1:
            break
        end = branch.index("|| true", start)
        blocks.append(branch[start:end])
        pos = end + len("|| true")
    return blocks


def test_hummingbird_asks_for_flatpak() -> None:
    branch = hummingbird_branch()
    packages: set[str] = set()
    for block in dnf_install_blocks(branch):
        packages |= {line.strip().rstrip("\\").strip() for line in block.splitlines()}
    assert "flatpak" in packages, (
        "the hummingbird base does not install flatpak, so once the package "
        "is published the image still will not carry it -- and without it "
        "customize-live.sh exits 1, no overlay or ISO can be built, and there "
        "is no installer app to launch"
    )


def test_flatpak_is_not_batched_with_xfsprogs() -> None:
    """The regression this guards against (tuna-os/tunaOS#1734): flatpak
    started publishing with a libfuse3.so.4 dependency that conflicts with
    the base image's own fuse3-libs. --skip-unavailable does not cover a
    dependency CONFLICT (only a name that resolves to nothing), so batching
    flatpak into the same transaction as xfsprogs let that conflict fail the
    whole transaction -- and xfsprogs with it, taking down every hummingbird
    build, base and desktop alike, for close to two weeks. flatpak must stay
    in its own transaction so its resolution can fail without ever touching
    xfsprogs."""
    branch = hummingbird_branch()
    blocks = dnf_install_blocks(branch)
    xfsprogs_block = next(b for b in blocks if "xfsprogs" in b)
    assert "flatpak" not in xfsprogs_block, (
        "flatpak is back in the same dnf transaction as xfsprogs -- a "
        "dependency conflict in flatpak's resolution (as opposed to it "
        "merely being unavailable) will fail the whole transaction and take "
        "xfsprogs, and therefore every hummingbird build, down with it"
    )
    flatpak_block = next(b for b in blocks if "flatpak" in b)
    assert "--skip-broken" in flatpak_block, (
        "flatpak's transaction needs --skip-broken, not just "
        "--skip-unavailable: the failure mode this guards is an "
        "unresolvable dependency CONFLICT, which --skip-unavailable does "
        "not cover"
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
