"""The niri greeter does not open the "Important Hotkeys" overlay.

bonito-niri first boot (iso-builder run 44609960988): niri's startup overlay,
every row "(not bound)", covered the login screen.
"""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build_scripts" / "install-zirconium.sh"


def test_greeter_config_skips_the_startup_hotkey_overlay():
    """Falsification: an empty greeter config shows the overlay at every boot."""
    body = re.search(r"cat >/etc/greetd/niri/config.kdl <<'EOF'\n(.*?)\nEOF", SCRIPT.read_text(), re.S)
    assert body and re.search(r"hotkey-overlay\s*\{\s*skip-at-startup\s*\}", body.group(1))
