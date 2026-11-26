"""COSMIC images ship a screen reader.

cosmic-session starts orca when the at-spi status turns on (Super+Alt+S, the
first page of the COSMIC installer), and the Fedora and EL COSMIC lists had
no orca: the shortcut and the installer's toggle started nothing. Fedora's
cosmic-session does not pull it in (dnf repoquery: nothing that COSMIC
requires or recommends needs orca).
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "tunaos.toml").read_text())


def test_the_rpm_cosmic_lists_offer_orca():
    groups = CONFIG["package_groups"]
    cosmic = CONFIG["desktops"]["cosmic"]["packages"]
    assert "orca" in groups["cosmic-fedora"]["optional"]
    # Fedora and Hummingbird take the group; ELN and EL10 have their own lists.
    assert "cosmic-fedora" in cosmic["fedora"]["include"]
    for base in ("eln", "el10"):
        assert "orca" in cosmic[base]["optional"], base
