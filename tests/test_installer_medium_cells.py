"""Each bonito medium cell equals what the installer recipe probe says (tunaOS#4905).

The file list below was measured on 2026-11-25 by reading the layers of
ghcr.io/tuna-os/bonito:{gnome,kde,cosmic,niri,xfce} (digests ecdd48c8, 008ce0f0,
6793503c, a2dcc3b1, c94c945d; label org.opencontainers.image.version 88a8a37)
from the registry. All five images carry the same facts:

    usr/lib/bootupd/updates/EFI.json
    usr/lib/efi/grub2/1:2.12-66.fc44/EFI/fedora/grubx64.efi
    usr/lib/efi/shim/16.1-7/EFI/fedora/shimx64.efi
    usr/lib/ostree/prepare-root.conf       [composefs] enabled = no
    usr/lib/os-release                     ID=fedora
    usr/lib/modules/7.3.4-200.fc44.x86_64

The test rebuilds that tree and runs the real probe,
live-iso/common/src/installer-recipe-backend.sh, with the btrfs opt-in of
#4921. Falsification: flip the pin to composefs enabled and the cell must
become ext4 or composefs-native; drop the opt-in and the filesystem is xfs,
which installer_medium.validate rejects for a non-EL base.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "live-iso/common/src/installer-recipe-backend.sh"

import importlib.util

spec = importlib.util.spec_from_file_location("c", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
medium = config.installer_medium_policy()

BOOTLOADER = {"grub2": "grub", "systemd": "systemd-boot"}


def bonito_tree(root: Path, composefs: str = "no") -> Path:
    for rel in (
        "usr/lib/bootupd/updates/EFI.json",
        "usr/lib/efi/grub2/1:2.12-66.fc44/EFI/fedora/grubx64.efi",
        "usr/lib/efi/shim/16.1-7/EFI/fedora/shimx64.efi",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")
    (root / "usr/lib/ostree").mkdir(parents=True, exist_ok=True)
    (root / "usr/lib/ostree/prepare-root.conf").write_text(
        f"[composefs]\nenabled = {composefs}\n\n[sysroot]\nreadonly = true\n"
    )
    (root / "usr/lib/os-release").write_text("ID=fedora\n")
    (root / "usr/lib/modules/7.3.4-200.fc44.x86_64").mkdir(parents=True)
    return root


def probe(root: Path, allow_btrfs: bool) -> dict:
    env = {**os.environ, "TUNAOS_INSTALLER_ALLOW_BTRFS": "1" if allow_btrfs else "0"}
    out = subprocess.run(
        ["bash", str(PROBE), str(root)], capture_output=True, text=True, env=env, check=True
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


@pytest.mark.parametrize("desktop", ["gnome", "kde", "cosmic", "niri", "xfce"])
def test_bonito_cell_matches_the_probe(tmp_path, desktop):
    got = probe(bonito_tree(tmp_path), allow_btrfs=True)
    row = medium.cell(config.load(), f"bonito:{desktop}")
    assert BOOTLOADER[got["bootloader"]] == row["bootloader"]
    assert ("composefs" if got["composeFsBackend"] == "true" else "ostree") == row["backend"]
    assert got["filesystem"] == row["filesystem"]


def test_without_the_opt_in_the_probe_says_xfs(tmp_path):
    assert probe(bonito_tree(tmp_path), allow_btrfs=False)["filesystem"] == "xfs"


def test_a_sealed_bonito_would_not_be_btrfs(tmp_path):
    # Kernel 7.3.4 predates the fs-verity fix (7.4-rc2): a sealed image gets ext4.
    got = probe(bonito_tree(tmp_path, composefs="yes"), allow_btrfs=True)
    assert got["filesystem"] == "ext4"
