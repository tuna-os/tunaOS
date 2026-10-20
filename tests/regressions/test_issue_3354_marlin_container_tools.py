"""tunaOS#3354: marlin base omitted distrobox and buildah.

On a booted Marlin desktop system (`BUILD_ID=4ace379`), `distrobox` and
`buildah` were absent while every other TunaOS variant installs both via
`build_scripts/10-base-packages.sh`, which `Containerfile.arch` never runs.
TunaOS is a container-first system and Distrobox is a core developer
workflow; marlin was the only desktop variant without it.

What must not recur: `Containerfile.arch` building a base image whose pacman
transaction names `podman`/`skopeo` but not `buildah`/`distrobox`.

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


def test_marlin_base_installs_container_tooling() -> None:
    packages = _arch_package_block()
    for package in ("buildah", "distrobox"):
        assert re.search(rf"^\s+{re.escape(package)}\s+\\$", packages, re.MULTILINE), (
            f"Containerfile.arch base-no-de does not install {package!r} "
            "(tunaOS#3354)"
        )
