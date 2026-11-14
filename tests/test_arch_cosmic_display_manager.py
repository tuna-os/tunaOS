"""Arch's COSMIC image logs in through cosmic-greeter, not stock greetd.

marlin:cosmic booted to a text `marlin login:` prompt (iso-builder run
43519052730, tunaOS#4537): greetd ran Arch's stock `agreety --cmd /bin/sh`
config and nothing enabled cosmic-greeter.service. The runtime contract passed
because it accepted greetd.service as the COSMIC display manager.
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _arch():
    return tomllib.loads((ROOT / "tunaos.toml").read_text())["desktops"]["cosmic-arch"]


def test_the_arch_cosmic_display_manager_is_cosmic_greeter():
    """Falsification: with display_manager = "greetd" this fails, and the
    installed marlin:cosmic image boots to agreety."""
    assert _arch()["display_manager"] == "cosmic-greeter"


def test_the_arch_cosmic_packages_carry_cosmic_greeter():
    """Falsification: dropping cosmic-greeter leaves `systemctl enable
    cosmic-greeter` with no unit."""
    assert "cosmic-greeter" in _arch()["packages"]["pacman"]["required"]


def test_the_runtime_contract_rejects_an_agreety_greetd_on_cosmic():
    """Falsification: restoring the xfce-only condition lets a COSMIC image
    with greetd's stock agreety config pass the contract."""
    text = (ROOT / "build_scripts/checks/e2e-runtime-checks.sh").read_text()
    assert '"$DESKTOP" == "cosmic"' in text
    assert "greetd launches a graphical greeter (not agreety/shell)" in text
