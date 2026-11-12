"""The installed XFCE system's LightDM opens the XFCE session, not another one.

bonito-xfce (iso-builder run 43187094834): the GUI-created account logged in
and landed in GNOME Shell showing "Welcome to Bonito". LightDM's user-session
defaults to "default", and the image ships a GNOME session too.
"""
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "build_scripts" / "desktop" / "xfce-greeter.sh"
CONF = "etc/lightdm/lightdm.conf.d/50-tunaos-xfce-session.conf"


def _pin(root):
    text = SCRIPT.read_text()
    match = re.search(r"^xfce_pin_lightdm_session\(\) {\n.*?^}\n", text, re.DOTALL | re.MULTILINE)
    assert match, "xfce_pin_lightdm_session not found"
    subprocess.run(["bash", "-c", match.group(0) + "xfce_pin_lightdm_session"],
                   env={"TUNAOS_XFCE_ROOT": str(root), "PATH": "/usr/bin:/bin"}, check=True, timeout=5)
    path = root / CONF
    return path.read_text() if path.exists() else None


@pytest.mark.parametrize("sessions,expected", [
    (["gnome.desktop", "xfce.desktop"], "xfce"),   # bonito: GNOME shares the image
    (["xfce4.desktop"], "xfce4"),
    (["xfce.desktop", "xfce4.desktop"], "xfce"),
])
def test_the_xfce_session_that_exists_is_pinned(tmp_path, sessions, expected):
    """Falsification: dropping the call leaves no conf and LightDM resolves
    'default' to whichever session sorts first (GNOME on bonito)."""
    sessions_dir = tmp_path / "usr/share/xsessions"
    sessions_dir.mkdir(parents=True)
    for name in sessions:
        (sessions_dir / name).write_text("[Desktop Entry]\n")
    assert _pin(tmp_path) == f"[Seat:*]\nuser-session={expected}\n"


def test_without_an_xfce_x11_session_nothing_is_pinned(tmp_path):
    """EL10 xfce-wayland ships only wayland-sessions; naming a missing session
    would break the greeter."""
    (tmp_path / "usr/share/xsessions").mkdir(parents=True)
    (tmp_path / "usr/share/xsessions/gnome.desktop").write_text("[Desktop Entry]\n")
    assert _pin(tmp_path) is None


def test_the_installed_lightdm_branch_pins_before_enabling():
    text = SCRIPT.read_text()
    branch = text[text.index("if command -v lightdm &>/dev/null; then\n\txfce_pin"):]
    assert branch.index("xfce_pin_lightdm_session") < branch.index("systemctl enable lightdm")
