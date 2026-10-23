"""tunaOS#3353: marlin base omitted essential core and inspection utilities.

On a booted Marlin desktop system (BUILD_ID=4ace379, IMAGE_ID="marlin"),
diff, less, lsusb, man, and fzf were missing from /usr/bin. Arch's upstream
base metapackage was slimmed down and omits diffutils, less, usbutils,
man-db, and fzf.

What must not recur: Containerfile.arch building a base image without
explicitly including diffutils, less, usbutils, man-db, and fzf in its base
package transaction.

Falsification: structural — removing diffutils, less, usbutils, man-db, or
fzf from Containerfile.arch's base-no-de pacman install block causes this test
to fail with the missing package name.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTAINERFILE = ROOT / "Containerfile.arch"

REQUIRED_PACKAGES = [
    "diffutils",
    "less",
    "usbutils",
    "man-db",
    "fzf",
]


def _base_packages() -> set[str]:
    assert CONTAINERFILE.is_file(), f"{CONTAINERFILE} missing"
    src = CONTAINERFILE.read_text(encoding="utf-8")
    assert "FROM ${BASE_IMAGE} AS base-no-de" in src, "base-no-de stage not found in Containerfile.arch"
    stage = src.split("FROM ${BASE_IMAGE} AS base-no-de", 1)[1]
    match = re.search(r"pacman -S\s+--noconfirm\s+--needed\s+([^\&]+)&&", stage, re.S)
    assert match, "pacman -S --noconfirm --needed command not found in base-no-de"
    block = match.group(1)
    packages = set()
    for line in block.splitlines():
        cleaned = line.strip().rstrip("\\").strip()
        if cleaned and not cleaned.startswith("#"):
            packages.add(cleaned)
    return packages


@pytest.mark.parametrize("package", REQUIRED_PACKAGES)
def test_marlin_base_includes_essential_utility(package: str) -> None:
    installed = _base_packages()
    assert package in installed, (
        f"Containerfile.arch base-no-de does not install {package!r}. "
        f"tunaOS#3353 requires diffutils, less, usbutils, man-db, and fzf in base."
    )
