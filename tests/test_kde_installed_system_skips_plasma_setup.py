"""Installed KDE images mask Plasma Setup's first-run wizard.

bonito-kde (iso-builder run 43894673694): both legs installed, then first boot
autologged into Plasma Setup's own `plasma-setup` user ("Welcome to Plasma
Desktop / Begin Setup") instead of showing the greeter with the account the
installer created.
"""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build_scripts" / "desktop" / "configure-desktop-runtime.sh"


def test_plasma_setup_is_masked_for_kde_when_present():
    """Falsification: without the mask Fedora 44 KDE images boot into the wizard."""
    text = SCRIPT.read_text()
    block = re.search(r'if \[\[ "\$desktop" == kde \]\] && systemctl list-unit-files plasma-setup\.service.*?\nfi\n',
                      text, re.S)
    assert block, "plasma-setup handling missing"
    assert "systemctl mask plasma-setup.service" in block.group(0)
