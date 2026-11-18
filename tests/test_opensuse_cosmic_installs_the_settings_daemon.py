"""openSUSE COSMIC installs cosmic-settings-daemon; cosmic-session cannot start without it.

sailfin-cosmic run 43590535657: the live journal shows
`cosmic-session: thread 'main' panicked at 'failed to start settings daemon: ... NotFound'`
on every greeter start, after cosmic-comp came up. The zypper list omitted the package
on the belief it was not packaged; Tumbleweed ships cosmic-settings-daemon and
cosmic-settings (tunaOS#4538).

Falsification: remove cosmic-settings-daemon from either list and the matching test fails.
"""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_primary_toml_zypper_list_has_the_settings_daemon():
    data = tomllib.loads((ROOT / "tunaos.toml").read_text())
    required = data["desktops"]["cosmic"]["packages"]["zypper"]["required"]
    assert "cosmic-settings-daemon" in required and "cosmic-settings" in required


def test_manifest_zypper_list_has_the_settings_daemon():
    manifest = json.loads((ROOT / "manifests/desktops/cosmic.yaml").read_text())
    zypper = manifest["packages"]["zypper"]
    assert "cosmic-settings-daemon" in zypper and "cosmic-settings" in zypper
