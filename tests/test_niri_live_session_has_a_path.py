"""The live niri greetd session command sets PATH.

greetd's source_profile is off, so nothing else gives the session a PATH.
marlin-niri (iso-builder run 43869008593) stayed on "Installing Marlin...
Starting..." for 20 minutes on both legs; the same empty PATH broke the XFCE
installer's `flatpak-spawn --host` calls (tunaOS#4620).
"""
import re
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1] / "live-iso" / "common" / "src" / "desktop-niri.sh"


def test_every_greetd_session_command_sets_path():
    """Falsification: a command without `env PATH=` leaves the session with no PATH."""
    commands = re.findall(r'^command = "(.*)"$', ADAPTER.read_text(), re.M)
    assert commands, "no greetd session command found"
    for command in commands:
        assert "env PATH=" in command and "/usr/bin" in command, command
