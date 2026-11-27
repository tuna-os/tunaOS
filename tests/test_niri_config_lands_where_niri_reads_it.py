"""The niri image installs its config where niri reads it (tunaOS#5053).

niri reads ~/.config/niri/config.kdl, else /etc/niri/config.kdl. bonito:niri
shipped /usr/share/niri/config.kdl only, so an installed user got niri's
built-in default (alacritty/fuzzel/swaylock hints, no shell; pod run on medium
45828155977, usb-6-desktop-status.png), and verify-branding-niri.sh passed on
the /usr/share copy. The shipped config also had no binds block: a user with
it would have had no keys at all.

Falsification: drop niri-system-config.sh from the manifests, or accept
/usr/share/niri in verify-branding-niri.sh, or drop the binds block.
"""
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "build_scripts/desktop/niri-system-config.sh"
CONFIG = ROOT / "system_files/usr/share/niri/config.kdl"
CHECK = ROOT / "build_scripts/checks/verify-branding-niri.sh"
SHELL_LINES = ('spawn-at-startup "waybar"', 'spawn-at-startup "swaync"',
               'spawn-at-startup "nm-applet"', 'spawn-at-startup "swaybg"')


def _sysroot(tmp_path, dms):
    root = tmp_path / "root"
    (root / "usr/share/niri").mkdir(parents=True)
    (root / "usr/share/niri/config.kdl").write_text(CONFIG.read_text())
    if dms:
        (root / "usr/bin").mkdir(parents=True)
        (root / "usr/bin/dms").write_text("#!/bin/sh\n")
        (root / "usr/bin/dms").chmod(0o755)
        (root / "usr/lib/systemd/user").mkdir(parents=True)
        (root / "usr/lib/systemd/user/dms.service").write_text("[Unit]\n")
    subprocess.run(["bash", "-euc", f'source "{HOOK}"'], check=True,
                   env={"PATH": "/usr/bin:/bin", "TUNAOS_SYSROOT": str(root)})
    return root


@pytest.mark.parametrize("name", ["niri", "niri-arch"])
def test_every_niri_desktop_runs_the_hook(name):
    # tunaos.toml generates manifests/desktops/<name>.yaml (post_install).
    config = tomllib.loads((ROOT / "tunaos.toml").read_text())
    assert "niri-system-config" in config["desktops"][name]["after_install"]
    operations = json.loads((ROOT / "scripts/lib/desktop_operations.json").read_text())
    assert operations["after"]["niri-system-config"] == HOOK.name


def test_the_shipped_config_has_keys():
    text = CONFIG.read_text()
    assert len(re.findall(r"^binds\s*\{", text, re.M)) == 1
    for key in ("Mod+Shift+Slash", "Mod+T ", "Mod+D ", "Mod+Q "):
        assert key in text, key


def test_without_dms_the_config_is_copied_whole(tmp_path):
    root = _sysroot(tmp_path, dms=False)
    out = root / "etc/niri/config.kdl"
    assert out.read_text() == CONFIG.read_text()
    assert oct(out.stat().st_mode & 0o777) == "0o644"
    assert not (root / "etc/systemd/user").exists()


def test_with_dms_the_shell_is_dms(tmp_path):
    root = _sysroot(tmp_path, dms=True)
    text = (root / "etc/niri/config.kdl").read_text()
    for line in SHELL_LINES:
        assert line not in text, line
    assert "session-shell" not in text
    assert re.search(r"^binds\s*\{", text, re.M)
    assert 'spawn-at-startup "wl-paste"' in text
    link = root / "etc/systemd/user/graphical-session.target.wants/dms.service"
    assert link.is_symlink() and str(link.readlink()) == "/usr/lib/systemd/user/dms.service"


def test_the_check_accepts_only_paths_niri_reads():
    text = CHECK.read_text()
    block = text[text.index('echo "== compositor defaults =="'):text.index('echo "== session registration =="')]
    assert "/usr/share/niri/config.kdl" not in block
    assert "/etc/niri/config.kdl" in block and "binds" in block
    assert "dms.service" in block
