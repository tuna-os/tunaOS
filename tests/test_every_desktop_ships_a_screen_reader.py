"""Every desktop image ships a screen reader.

COSMIC's Super+Alt+S, Plasma's Meta+Alt+S, the COSMIC installer's first page
(tunaOS#5012) and GNOME's top bar turn on the at-spi screen-reader status,
and the session starts orca on it. Fedora installs no weak dependencies
(01-workarounds.sh), so orca came only where a list named it: the KDE, XFCE,
niri, COSMIC, Pantheon and several GNOME lists did not. This test makes the
list name it, so a change cannot drop it again without failing here.

dnf lists carry it as optional (install_available: a repository without it
does not stop the build); apt, pacman and zypper lists have no optional
tier, and every one of their repositories has orca. Gentoo (emerge) is left
out: orca needs brltty[python] there, which the Tuna desktop sets and the
others do not.
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "tunaos.toml").read_text())
GROUPS = CONFIG["package_groups"]
DNF = {"fedora", "rawhide", "eln", "el10", "hummingbird"}


def lists():
    for desktop, spec in CONFIG["desktops"].items():
        for base, section in spec.get("packages", {}).items():
            if not isinstance(section, dict) or base == "emerge":
                continue
            if any(k in section for k in ("required", "optional", "include", "groups")):
                yield desktop, base, section


def named(section):
    names = set(section.get("required", [])) | set(section.get("optional", []))
    for group in section.get("include", []):
        names |= set(GROUPS[group].get("required", [])) | set(GROUPS[group].get("optional", []))
    return {n.split("/")[-1] for n in names}


@pytest.mark.parametrize("desktop, base, section", list(lists()), ids=lambda v: v if isinstance(v, str) else "")
def test_the_desktop_list_names_a_screen_reader(desktop, base, section):
    assert "orca" in named(section), f"{desktop} on {base} has no screen reader"


def test_dnf_lists_take_it_as_optional():
    for desktop, base, section in lists():
        if base in DNF and "orca" not in set(section.get("required", [])):
            assert "orca" in named(section), (desktop, base)


def test_every_desktop_is_covered():
    desktops = {d for d, _b, _s in lists()}
    for expected in ("cosmic", "gnome", "kde", "niri", "xfce", "pantheon", "tuna"):
        assert expected in desktops
