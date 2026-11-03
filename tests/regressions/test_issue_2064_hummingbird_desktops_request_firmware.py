"""tunaOS#2064: Hummingbird desktop images shipped without device firmware.

The 2026-08-25 image manifests contained no Linux firmware, wireless
regulatory database, wireless tooling, or NetworkManager Wi-Fi plugin. QEMU
could not expose the omission because virtio devices need no vendor firmware.
The second pass adds SOF and ALSA firmware for laptop audio.
This test holds the hardware package contract for every supported
Hummingbird desktop while leaving the deliberately desktop-less base alone.

Falsification: structural -- remove any package below from GNOME or COSMIC's
Hummingbird package list and this test fails as the unfixed tree did.
"""
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "firmware_config", ROOT / "scripts/lib/tunaos_config.py"
)
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)

HARDWARE_BASELINE = {
    "NetworkManager-wifi",
    "linux-firmware",
    "alsa-sof-firmware",
    "alsa-firmware",
    "amd-gpu-firmware",
    "intel-gpu-firmware",
    "iwlwifi-mvm-firmware",
    "wireless-regdb",
    "iw",
}


@pytest.mark.parametrize("desktop", ["gnome", "cosmic"])
def test_supported_hummingbird_desktops_request_the_hardware_baseline(desktop: str):
    document = config.load(ROOT / "tunaos.toml")
    # Expand shared groups through the same policy reader as the installer.
    contract = config.package_policy().resolve(
        {key: document[key] for key in ("package_groups", "desktops")},
        desktop, manager="dnf", os_id="hummingbird", hummingbird=True
    )
    packages = set(contract["sections"][0][1]["required"])

    assert HARDWARE_BASELINE <= packages, (
        f"{desktop} is missing Hummingbird's hardware baseline: "
        f"{sorted(HARDWARE_BASELINE - packages)}"
    )
