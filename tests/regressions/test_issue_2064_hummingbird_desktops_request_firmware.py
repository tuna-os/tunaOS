"""tunaOS#2064: Hummingbird desktop images shipped without device firmware.

The 2026-08-25 image manifests contained no Linux firmware, wireless
regulatory database, wireless tooling, or NetworkManager Wi-Fi plugin. QEMU
could not expose the omission because virtio devices need no vendor firmware.
This test holds the first-pass hardware package contract for every supported
Hummingbird desktop while leaving the deliberately desktop-less base alone.

Falsification: structural -- remove any package below from GNOME or COSMIC's
Hummingbird package list and this test fails as the unfixed tree did.
"""
from pathlib import Path

import pytest


yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
DESKTOPS = ROOT / "manifests" / "desktops"

HARDWARE_BASELINE = {
    "NetworkManager-wifi",
    "linux-firmware",
    "amd-gpu-firmware",
    "intel-gpu-firmware",
    "iwlwifi-mvm-firmware",
    "wireless-regdb",
    "iw",
}


@pytest.mark.parametrize("desktop", ["gnome", "cosmic"])
def test_supported_hummingbird_desktops_request_the_hardware_baseline(desktop: str):
    manifest = yaml.safe_load((DESKTOPS / f"{desktop}.yaml").read_text())
    packages = set(manifest["packages"]["hummingbird"]["packages"])

    assert HARDWARE_BASELINE <= packages, (
        f"{desktop} is missing Hummingbird's hardware baseline: "
        f"{sorted(HARDWARE_BASELINE - packages)}"
    )
