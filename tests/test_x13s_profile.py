"""Build-matrix and architecture contract for the X13s W1 profile (#3377)."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
RESOLVER = ROOT / "scripts" / "resolve-flavor.sh"
OVERLAY = ROOT / "build_scripts" / "overlay" / "x13s.sh"
INVENTORY = ROOT / "build_scripts" / "overlay" / "lib" / "x13s_inventory.sh"

def resolve(variant: str, flavor: str) -> dict[str, str]:
    proc = subprocess.run(
        [str(RESOLVER), variant, flavor],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    values = {}
    for line in proc.stdout.splitlines():
        key, raw = line.split("=", 1)
        values[key] = shlex.split(raw)[0]
    return values


def test_bonito_x13s_is_an_arm64_only_non_artifact_cell():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    bonito = next(v for v in config["variants"] if v["id"] == "bonito")
    profile = next(f for f in bonito["flavors"] if f["id"] == "gnome-x13s")

    assert profile["platforms"] == ["linux/arm64"]
    assert profile["stage"] == 3
    assert profile["build_image"] is True
    assert profile["build_iso"] is False
    assert profile["build_qcow2"] is False
    assert profile["luks_e2e"] is False


def test_bonito_x13s_routes_to_the_gnome_hardware_overlay():
    values = resolve("bonito", "gnome-x13s")

    assert values["CONTAINERFILE"] == "Containerfile.overlay"
    assert values["OVERLAY_TYPE"] == "x13s"
    assert values["DESKTOP_FLAVOR"] == "desktop"
    assert values["PARENT_FLAVOR"] == "gnome"


def test_x13s_suffix_is_not_admitted_on_another_variant():
    values = resolve("albacore", "gnome-x13s")

    assert values["CONTAINERFILE"] == "Containerfile.el10"
    assert values["OVERLAY_TYPE"] == ""
    assert values["DESKTOP_FLAVOR"] == "gnome-x13s"
    assert values["PARENT_FLAVOR"] == ""


def test_x13s_overlay_rejects_a_wrong_architecture(tmp_path: Path):
    uname = tmp_path / "uname"
    uname.write_text("#!/usr/bin/env bash\necho x86_64\n", encoding="utf-8")
    uname.chmod(0o755)
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}

    proc = subprocess.run(
        [str(OVERLAY)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "only applies to aarch64 builds" in proc.stderr


def test_x13s_firmware_inventory_follows_usable_symlinks(tmp_path: Path):
    payload = tmp_path / "payload"
    payload.mkdir()
    compressed = payload / "amss.bin.xz"
    compressed.write_text("firmware", encoding="utf-8")

    firmware = tmp_path / "firmware"
    firmware.mkdir()
    (firmware / compressed.name).symlink_to(compressed)

    for directory in (firmware, tmp_path / "firmware-link"):
        if directory != firmware:
            directory.symlink_to(firmware, target_is_directory=True)
        expected = directory / "amss.bin"
        proc = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", 'source "$1"; inventory_file "$2"', "bash", str(INVENTORY), str(expected)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith(f"PRESENT {expected} -> ")
        assert str(directory / compressed.name) in proc.stdout


@pytest.mark.parametrize("suffix", ["", ".xz", ".zst"])
def test_x13s_firmware_inventory_accepts_supported_payloads(tmp_path: Path, suffix: str):
    expected = tmp_path / "amss.bin"
    expected.with_name(expected.name + suffix).write_bytes(b"firmware")
    assert firmware_inventory(expected).startswith(f"PRESENT {expected} -> ")


@pytest.mark.parametrize("suffix", [".bak", ".sig", ".xz.bak", ".zst.sig", ".gz"])
def test_x13s_firmware_inventory_rejects_non_payload_suffixes(tmp_path: Path, suffix: str):
    expected = tmp_path / "amss.bin"
    expected.with_name(expected.name + suffix).write_bytes(b"not usable firmware")
    assert firmware_inventory(expected) == f"MISSING {expected}\n"


def test_x13s_firmware_inventory_rejects_dangling_links(tmp_path: Path):
    expected = tmp_path / "amss.bin"
    expected.with_name("amss.bin.xz").symlink_to(tmp_path / "absent")
    assert firmware_inventory(expected) == f"MISSING {expected}\n"


def firmware_inventory(expected: Path) -> str:
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", 'source "$1"; inventory_file "$2"', "bash", str(INVENTORY), str(expected)],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
