"""The live ISO must fetch and deploy the installer for its OWN architecture.

A flatpak bundle carries refs for one architecture. The published release
asset was x86_64-only and its name carried no arch, so an aarch64 ISO
downloaded it, imported `app/org.bootcinstaller.Installer/x86_64/master`, and
then found nothing matching the host:

    error: Nothing matches org.bootcinstaller.Installer in remote installer-local

Measured on gurnard run 32495176056, `iso:pantheon (linux-arm64)`. The arm64
ISO could therefore never carry the installer — and nothing downstream of it,
including the installer smoke gate and the walkthrough, was ever exercisable
on that arch.

Reading that block turned up a SECOND hardcoded arch a few lines down: the
active-symlink repair globbed `/var/lib/flatpak/app/<app>/x86_64`, which on
aarch64 is a directory that does not exist, so the repair silently did
nothing. Both are pinned here, because one being fixed without the other
leaves the ISO booting to an installer that flatpak cannot launch.

The x86_64 asset name stays bare on purpose: every existing consumer fetches
`releases/latest/download/org.bootcinstaller.Installer.flatpak`, and renaming
it would break them all to no benefit. Paired change: tuna-os/bootc-installer#25.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "live-iso" / "common" / "src" / "customize-live.sh"


def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_the_asset_name_is_chosen_from_the_host_arch():
    text = script()
    assert '_installer_asset="org.bootcinstaller.Installer.flatpak"' in text
    assert '_installer_asset="org.bootcinstaller.Installer-$(uname -m).flatpak"' in text


def test_x86_64_keeps_the_bare_asset_name():
    """Downstreams fetch that exact URL; the arch suffix is for everyone else."""
    text = script()
    guard = re.search(r'if \[\[ "\$\(uname -m\)" != "x86_64" \]\]; then', text)
    assert guard, "the suffix is not gated on being a non-x86_64 host"
    bare = text.index('_installer_asset="org.bootcinstaller.Installer.flatpak"')
    assert bare < guard.start(), "x86_64 must be the default, not the exception"


def test_both_download_urls_use_the_resolved_asset():
    """The fallback mirror has to agree with the primary — fetching a bare
    name there would reintroduce the bug for anyone who hits the fallback."""
    text = script()
    urls = re.findall(r"releases/latest/download/([^\"]+)", text)
    assert urls, "no release download URLs found"
    assert all(u == "${_installer_asset}" for u in urls), urls


def test_a_missing_arch_asset_fails_by_name():
    """Otherwise the next failure reads as 'Nothing matches ... in remote
    installer-local' three commands later, which looks like a corrupt
    download rather than an asset that was never published."""
    text = script()
    assert 'echo "ERROR: no ${_installer_asset} published for $(uname -m)"' in text


def test_the_deploy_path_is_not_hardcoded_to_x86_64():
    """The second bug in the same block: flatpak deploys under the host arch,
    so a hardcoded x86_64 made the active-symlink repair a silent no-op on
    aarch64."""
    text = script()
    assert '_app_arch_dir="/var/lib/flatpak/app/${INSTALLER_APP}/$(uname -m)"' in text
    assert "/var/lib/flatpak/app/${INSTALLER_APP}/x86_64" not in text


def test_no_arch_is_hardcoded_anywhere_in_the_installer_block():
    """A sweep rather than a spot check — either hardcoding alone is enough to
    break the arm64 ISO."""
    text = script()
    start = text.index("INSTALLER_FLATPAK_FILE=")
    end = text.index('rm -rf "${INSTALLER_LOCAL_REPO}"', start)
    # CODE only. The comments in this block quote the incident, including
    # `app/org.bootcinstaller.Installer/x86_64/master` — scanning them would
    # make the test fail on its own explanation.
    code = "\n".join(
        line for line in text[start:end].splitlines()
        if not line.lstrip().startswith("#")
    )
    # The one legitimate literal is the guard that keeps x86_64 on the bare
    # asset name; everything else must derive the arch at runtime.
    code = code.replace('!= "x86_64"', "")
    assert "x86_64" not in code, "a literal x86_64 remains in the installer block"
