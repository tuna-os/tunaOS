"""tunaOS#3355: marlin base omitted modern audio support.

On a booted Marlin desktop system (`BUILD_ID=4ace379`), `sof-firmware` and
`pipewire-alsa` were not installed: modern laptop audio DSPs had no firmware
and ALSA clients could not route into PipeWire, while `pipewire` and
`wireplumber` were present.

What must not recur: `Containerfile.arch` installing `linux-firmware` without
`sof-firmware`, or `pipewire` without `pipewire-alsa`.

Falsification: structural — removing either package from the base-no-de
pacman install block fails this test.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCH_CONTAINERFILE = ROOT / "Containerfile.arch"


def _arch_package_block() -> str:
    source = ARCH_CONTAINERFILE.read_text(encoding="utf-8")
    start = source.index("pacman -S --noconfirm --needed")
    end = source.index("pacman -Scc --noconfirm", start)
    return source[start:end]


def test_marlin_base_installs_audio_firmware_and_alsa_bridge() -> None:
    packages = _arch_package_block()
    for package in ("sof-firmware", "pipewire-alsa"):
        assert re.search(rf"^\s+{re.escape(package)}\s+\\$", packages, re.MULTILINE), (
            f"Containerfile.arch base-no-de does not install {package!r} "
            "(tunaOS#3355)"
        )
