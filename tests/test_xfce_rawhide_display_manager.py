"""Rawhide's XFCE image runs LightDM and does not install gdm.

The Fedora XFCE profile installs gdm and wires it into graphical.target,
while the xfce-desktop group's lightdm owns display-manager.service. Both
start. On Rawhide gdm 51 cannot start the X11-only XFCE session, so it wins
the race and the live ISO autologins nowhere: bonito-rawhide-xfce
(iso-builder run 43586178095) reached "Display output is not active".
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _xfce():
    return tomllib.loads((ROOT / "tunaos.toml").read_text())["desktops"]["xfce"]


def test_the_rawhide_xfce_display_manager_is_lightdm():
    """Falsification: delete [desktops.xfce.packages.rawhide], or set its
    display_manager to "gdm", and this fails; the live ISO is black again."""
    assert _xfce()["packages"]["rawhide"]["display_manager"] == "lightdm"


def test_the_rawhide_xfce_packages_carry_lightdm_and_an_x_server_but_not_gdm():
    """Falsification: re-adding gdm to the rawhide list starts a second
    display manager; dropping xorg-x11-server-Xorg leaves lightdm no server."""
    packages = _xfce()["packages"]["rawhide"]["required"]
    for name in ("lightdm", "lightdm-gtk-greeter", "xorg-x11-server-Xorg"):
        assert name in packages
    assert "gdm" not in packages


def test_the_stable_fedora_xfce_profile_is_unchanged():
    """The override is Rawhide only: bonito:xfce is qualified with gdm in its
    package list. Falsification: moving the change into the fedora section
    fails this."""
    fedora = _xfce()["packages"]["fedora"]
    assert "gdm" in fedora["required"]
    assert "display_manager" not in fedora
    assert _xfce()["display_manager"] == "gdm"
