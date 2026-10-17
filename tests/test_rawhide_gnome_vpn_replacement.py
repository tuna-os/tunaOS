"""Retired vpnc must become a required native plugin, scoped to Rawhide."""

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "desktop", ["gnome", "kde", "niri", "cosmic", "xfce"],
)
@pytest.mark.parametrize(
    "section,release,expected",
    [
        ("fedora", "rawhide", "NetworkManager-libreswan-gnome"),
        ("fedora", "44", "NetworkManager-vpnc-gnome"),
        ("hummingbird", "rawhide", "NetworkManager-vpnc-gnome"),
        ("eln", "rawhide", "NetworkManager-vpnc-gnome"),
        ("el10", "rawhide", "NetworkManager-vpnc-gnome"),
    ],
)
def test_required_vpn_selection(section, release, expected, desktop):
    source = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    start = source.index('\tif [[ "${_TD_OS}" == fedora && "$(detect_fedora_ver)" == rawhide ]]; then')
    end = source.index('\n\treadarray -t _TD_EXCLUDES', start)
    script = (
        'set -euo pipefail\n'
        f'_TD_DESKTOP={desktop}\n'
        f'_TD_OS={section}\n'
        f'detect_fedora_ver() {{ echo {release}; }}\n'
        '_TD_PKGS=(gnome-shell NetworkManager-vpnc-gnome NetworkManager-openvpn-gnome)\n'
        + source[start:end]
        + '\nprintf "%s\\n" "${_TD_PKGS[@]}"\n'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    expected_packages = ["gnome-shell", expected, "NetworkManager-openvpn-gnome"]
    if section == "fedora" and release == "rawhide" and desktop == "gnome":
        expected_packages += ["gnome-keyring", "gnome-keyring-pam"]
    assert result.stdout.splitlines() == expected_packages
