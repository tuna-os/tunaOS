"""tunaOS#5149: the Pantheon image ships its shell, not only the compositor.

gurnard:pantheon run 46122173243 reached a user session whose picture was
wallpaper and a lone '+': wingpanel had no indicators (no
/usr/lib/<arch>/wingpanel) and the dock's pinned launchers had no .desktop.
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDICATORS = {
    "wingpanel-indicator-bluetooth",
    "wingpanel-indicator-datetime",
    "wingpanel-indicator-keyboard",
    "wingpanel-indicator-network",
    "wingpanel-indicator-nightlight",
    "wingpanel-indicator-notifications",
    "wingpanel-indicator-power",
    "wingpanel-indicator-sound",
}
# The apps behind the dock's default launchers (io.elementary.dock gschema).
DOCK_APPS = {
    "pantheon-files",
    "epiphany-browser",
    "io.elementary.mail",
    "io.elementary.tasks",
    "maya-calendar",
    "io.elementary.music",
    "io.elementary.videos",
    "pantheon-photos",
    "appcenter",
}


def required():
    cfg = tomllib.loads((ROOT / "tunaos.toml").read_text())
    return set(cfg["desktops"]["pantheon"]["packages"]["apt"]["required"])


def test_the_shell_meta_and_every_wingpanel_indicator_are_installed():
    pkgs = required()
    assert "pantheon-shell" in pkgs
    assert "io.elementary.quick-settings" in pkgs
    assert INDICATORS <= pkgs, INDICATORS - pkgs


def test_every_default_dock_launcher_has_its_app():
    assert DOCK_APPS <= required(), DOCK_APPS - required()


def test_the_list_stays_a_list_of_unique_names():
    cfg = tomllib.loads((ROOT / "tunaos.toml").read_text())
    names = cfg["desktops"]["pantheon"]["packages"]["apt"]["required"]
    # orca is listed twice upstream of this change; nothing new may repeat.
    new = [n for n in names if n in INDICATORS | DOCK_APPS | {"pantheon-shell", "io.elementary.quick-settings", "elementary-artwork", "io.elementary.settings"}]
    assert len(new) == len(set(new))
