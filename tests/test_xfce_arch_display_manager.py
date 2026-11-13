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


def test_no_xfce_hook_edits_gdm_session_entries_any_more():
    assert "xfce-gdm-session" not in _arch()["after_install"]
    assert not (ROOT / "build_scripts/desktop/xfce-gdm-session.sh").exists()
