"""The Pantheon session needs gnome-settings-daemon; the apt list must name it.

gurnard:pantheon's live session showed "Oh no! Something has gone wrong." The
live-serial diagnostic (iso-builder run 43540046366) read the user journal:

    gnome-session-binary: WARNING: Unable to find required component
    'org.gnome.SettingsDaemon.A11ySettings' (and 15 more)
    gnome-session-failed --allow-logout

pantheon-xsession-settings only Depends on gnome-session-bin, gala and
pantheon-shell. The archive package that ships the org.gnome.SettingsDaemon.*
components (gnome-settings-daemon) is named by nothing in
desktops.pantheon, and every apt install here runs --no-install-recommends.

Falsification: delete "gnome-settings-daemon" from [desktops.pantheon.packages.apt]
required in tunaos.toml and test_pantheon_lists_the_session_daemons fails.
"""
from __future__ import annotations

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SESSION_DAEMONS = {"gnome-settings-daemon", "at-spi2-core"}


def _pantheon_apt() -> set[str]:
    doc = tomllib.loads((ROOT / "tunaos.toml").read_text(encoding="utf-8"))
    return set(doc["desktops"]["pantheon"]["packages"]["apt"]["required"])


def test_the_scan_reads_the_pantheon_list():
    # A selector that matches nothing would make the assertion below vacuous.
    assert {"gala", "pantheon-xsession-settings"} <= _pantheon_apt()


def test_pantheon_lists_the_session_daemons():
    missing = SESSION_DAEMONS - _pantheon_apt()
    assert not missing, (
        f"desktops.pantheon omits {sorted(missing)}: gnome-session then logs "
        "'Unable to find required component org.gnome.SettingsDaemon.*' and shows "
        "the 'Oh no! Something has gone wrong' screen before gala starts"
    )
