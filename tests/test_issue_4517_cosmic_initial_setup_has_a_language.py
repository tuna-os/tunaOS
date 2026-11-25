"""COSMIC Initial Setup lists no language when only C.utf8 is installed (#4517).

Same cause as GNOME (#4289): the base ships glibc-minimal-langpack, so the
language page is empty and Next stays disabled. Every COSMIC base must install
a real locale package.
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALE = {"locales-all", "glibc-all-langpacks", "glibc-langpack-en"}


def _pkgs(name):
    cfg = tomllib.loads((ROOT / "tunaos.toml").read_text())
    return set(cfg["desktops"]["cosmic"]["packages"][name]["required"])


def test_every_cosmic_base_installs_a_real_locale():
    for base in ("apt", "el10", "eln", "hummingbird"):
        assert _pkgs(base) & LOCALE, f"cosmic/{base} installs no locale package"
