"""Arch's XFCE image logs in through LightDM, not GDM.

GDM 50 no longer starts X11 sessions, and Arch has no Wayland XFCE session.
marlin-xfce (iso-builder run 43504493064) booted to the GDM greeter with an
`AutomaticLogin=liveuser` config and never logged in. gdm also pulls in
gnome-shell and gnome-session, so the image carried GNOME sessions as well
(run 43429585359).
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _arch():
    return tomllib.loads((ROOT / "tunaos.toml").read_text())["desktops"]["xfce-arch"]


def test_the_arch_xfce_display_manager_is_lightdm():
    """Falsification: with display_manager = "gdm" this fails, and the live
    ISO stops at the GDM greeter."""
    assert _arch()["display_manager"] == "lightdm"


def test_the_arch_xfce_packages_carry_lightdm_and_an_x_server_but_not_gdm():
    """Falsification: re-adding gdm brings back gnome-shell's session entries;
    dropping xorg-server leaves lightdm with no server for its greeter."""
    packages = _arch()["packages"]["pacman"]["required"]
    for name in ("lightdm", "lightdm-gtk-greeter", "xorg-server"):
        assert name in packages
    assert "gdm" not in packages


def test_the_arch_xfce_desktop_no_longer_runs_the_gdm_session_hook():
    """The hook stays registered for one merge: scripts/check-package-sources.py
    parses the base revision's tunaos.toml with this revision's operation
    registry, so deleting an operation that the base still names fails Lint.
    A follow-up deletes the script and its registry entry."""
    assert "xfce-gdm-session" not in _arch()["after_install"]
