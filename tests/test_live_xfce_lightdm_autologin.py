"""The XFCE live adapter's LightDM autologin names a session that exists.

Without autologin-session LightDM falls back to user-session, whose built-in
default is "default". Fedora 44 sets none and ships only
/usr/share/xsessions/xfce.desktop, so bonito-xfce (iso-builder run
42897588043) sat at the LightDM greeter on every frame and the installer
never started.
"""
import re
import subprocess
from pathlib import Path

import pytest

ADAPTER = Path(__file__).resolve().parents[1] / "live-iso" / "common" / "src" / "desktop-xfce.sh"


def _function(name):
    text = ADAPTER.read_text()
    match = re.search(rf"^{name}\(\) {{\n.*?^}}\n", text, re.DOTALL | re.MULTILINE)
    assert match, f"{name} not found in {ADAPTER.name}"
    return match.group(0)


def _session(directory):
    result = subprocess.run(
        ["bash", "-c", _function("xfce_x11_session") + 'xfce_x11_session "$1"', "t", str(directory)],
        capture_output=True, text=True, check=False, timeout=5)
    return result.returncode, result.stdout.strip()


@pytest.mark.parametrize("files,expected", [
    (["xfce.desktop"], "xfce"),                       # Fedora 44 (measured), Debian, Ubuntu
    (["xfce4.desktop"], "xfce4"),
    (["xfce.desktop", "xubuntu.desktop"], "xfce"),
])
def test_the_session_file_that_exists_is_named(tmp_path, files, expected):
    for name in files:
        (tmp_path / name).write_text("[Desktop Entry]\n")
    assert _session(tmp_path) == (0, expected)


def test_no_xfce_session_is_a_failure_not_a_guess(tmp_path):
    (tmp_path / "default.desktop").write_text("[Desktop Entry]\n")
    assert _session(tmp_path)[0] != 0


def test_the_lightdm_autologin_config_carries_the_session():
    text = ADAPTER.read_text()
    block = text[text.index("50-live-autologin.conf <<"):text.index("\nLIGHTDMEOF", text.index("50-live-autologin.conf <<"))]
    assert "autologin-user=liveuser" in block
    assert "autologin-session=${_xfce_xsession}" in block
    # Unquoted heredoc: the session name must be expanded, not written literally.
    assert "<<LIGHTDMEOF" in block and "<<'LIGHTDMEOF'" not in block
