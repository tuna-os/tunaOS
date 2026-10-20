"""The live ISO must fetch the installer bundle for its target architecture.

The published x86_64 bundle keeps its historical bare filename. Other
architectures carry an explicit suffix. The script exposes a side-effect-free
probe so this contract is tested as behavior rather than source text.
"""

from __future__ import annotations

import os
import pytest
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


@pytest.mark.parametrize(
    ("arch", "expected"),
    [
        ("amd64", "org.bootcinstaller.Installer.flatpak"),
        ("linux/amd64", "org.bootcinstaller.Installer.flatpak"),
        ("linux/amd64/v2", "org.bootcinstaller.Installer.flatpak"),
        ("arm64", "org.bootcinstaller.Installer-aarch64.flatpak"),
        ("linux/arm64", "org.bootcinstaller.Installer-aarch64.flatpak"),
    ],
)
def test_matrix_architecture_aliases_select_the_published_asset(arch: str, expected: str) -> None:
    assert installer_asset(arch) == expected


def test_unknown_architecture_fails_closed() -> None:
    env = os.environ | {"TUNA_ASSET_NAME_ONLY": "1", "TUNA_INSTALLER_ARCH": "mips64"}

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "unsupported installer architecture: mips64" in result.stderr
    assert result.stdout == ""


def test_metadata_only_requires_disposable_root_before_writes(
    tmp_path: Path,
) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    marker_calls = tmp_path / "marker-calls"
    for command in ("mkdir", "touch"):
        stub = fakebin / command
        stub.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '%s\\n' \"$*\" >>{str(marker_calls)!r}\n"
            "exit 99\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    env = os.environ | {
        "PATH": f"{fakebin}:{os.environ['PATH']}",
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
    assert not marker_calls.exists()
