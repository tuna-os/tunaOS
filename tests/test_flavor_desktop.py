"""Overlay flavor suffixes have one shared desktop normalization contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/lib/flavor-desktop.sh"


@pytest.mark.parametrize(
    ("flavor", "expected"),
    [
        ("gnome", "gnome"),
        ("gnome-nvidia", "gnome"),
        ("kde-nvidia-hwe", "kde"),
        ("gnome-x13s", "gnome"),
        ("base-hwe", "base"),
    ],
)
def test_shared_desktop_normalization(flavor: str, expected: str) -> None:
    result = subprocess.run(
        [
            "bash",
            "-euc",
            'source "$1"; tunaos_desktop_flavor "$2"',
            "flavor-desktop-test",
            str(HELPER),
            flavor,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == expected
