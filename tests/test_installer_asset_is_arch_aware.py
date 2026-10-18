"""The live ISO must fetch the installer bundle for its target architecture.

The published x86_64 bundle keeps its historical bare filename. Other
architectures carry an explicit suffix. The script exposes a side-effect-free
probe so this contract is tested as behavior rather than source text.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "live-iso" / "common" / "src" / "customize-live.sh"


def installer_asset(arch: str) -> str:
    env = os.environ | {
        "TUNA_ASSET_NAME_ONLY": "1",
        "TUNA_INSTALLER_ARCH": arch,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def test_x86_64_keeps_the_compatible_bare_asset_name() -> None:
    assert installer_asset("x86_64") == "org.bootcinstaller.Installer.flatpak"


def test_aarch64_uses_the_target_specific_asset_name() -> None:
    assert (
        installer_asset("aarch64")
        == "org.bootcinstaller.Installer-aarch64.flatpak"
    )


def test_metadata_only_requires_disposable_root_before_writes() -> None:
    env = os.environ | {
        "TUNA_METADATA_ONLY": "1",
        "TUNA_INSTALLER_APP": "org.bootcinstaller.Installer",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "TUNA_SESSION_ROOT is required" in result.stderr
