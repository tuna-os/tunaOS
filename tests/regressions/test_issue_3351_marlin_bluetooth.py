"""tunaOS#3351: Marlin shipped without usable Bluetooth.

The measured `marlin:gnome` image had the adapter present and unblocked, but
`bluetooth.service` was inactive with `preset: disabled`, and `bluetoothctl`
was absent because `bluez-utils` was not installed. This test holds the Arch
base package contract, the explicit service enablement, and the first-boot
preset together so the same image cannot ship that combination again.

Falsification: structural. Remove either `bluez` or `bluez-utils` from the
Arch package block, remove the pacman-path `safe_enable`, or remove the
preset directive; the corresponding assertion fails.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCH_CONTAINERFILE = ROOT / "Containerfile.arch"
SERVICES = ROOT / "build_scripts/40-services.sh"
PRESET = ROOT / "system_files/usr/lib/systemd/system-preset/50-tunaos.preset"


def _arch_package_block() -> str:
    source = ARCH_CONTAINERFILE.read_text(encoding="utf-8")
    start = source.index("pacman -S --noconfirm --needed")
    end = source.index("pacman -Scc --noconfirm", start)
    return source[start:end]


def _pacman_service_block() -> str:
    source = SERVICES.read_text(encoding="utf-8")
    start = source.index(
        'if [[ "${PKG_MGR:-}" == "pacman" ]] || command -v zypper'
    )
    end = source.index("# ── dnf (RPM / Universal-Blue)", start)
    return source[start:end]


def _preset_directives() -> dict[str, str]:
    directives: dict[str, str] = {}
    for line in PRESET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        verb, _, unit = line.partition(" ")
        directives[unit.strip()] = verb
    return directives


def test_marlin_installs_bluetooth_packages() -> None:
    packages = _arch_package_block()
    for package in ("bluez", "bluez-utils"):
        assert re.search(rf"^\s+{re.escape(package)}\s+\\$", packages, re.MULTILINE)


def test_marlin_explicitly_enables_bluetooth_on_pacman_bases() -> None:
    assert re.search(
        r"^\s*safe_enable bluetooth\.service\s*$",
        _pacman_service_block(),
        re.MULTILINE,
    )


def test_bluetooth_survives_first_boot_preset_application() -> None:
    assert _preset_directives().get("bluetooth.service") == "enable"
