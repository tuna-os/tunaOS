"""The live SDDM config must actually be read on a base that ships none.

SDDM's ConfigBase::load() skips loading entirely unless the newest mtime among
its config files and directories is a valid QDateTime, and Qt reports an mtime
of 0 as invalid. The browser ISO builder grafts the live overlay with every
mtime at 0, and grouper (Ubuntu) ships no SDDM config of its own, so the
grouper:kde pilot ISO ran SDDM on built-in defaults (DisplayServer=x11, no
autologin), tried to start an X server the image does not have, and showed a
black screen with no session and no installer (tunaOS#4459).

These tests check the adapter's fix: a boot-time unit that gives the config
directories a real mtime before the display manager starts, and a drop-in
whose keys sit in the sections SDDM reads them from.
"""

from __future__ import annotations

import configparser
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "live-iso" / "common" / "src" / "desktop-kde.sh"


def heredoc(tag: str) -> str:
    text = ADAPTER.read_text(encoding="utf-8")
    m = re.search(r"<<'?" + tag + r"'?\n(.*?)\n" + tag + r"\n", text, re.DOTALL)
    assert m, f"heredoc {tag} not found in desktop-kde.sh"
    return m.group(1)


def unit() -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read_string(heredoc("DMCFGEOF"))
    return cp


def test_compositor_command_is_in_the_wayland_section():
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read_string(heredoc("SDDMEOF").replace("${_kde_session}", "plasma"))
    assert cp["General"]["DisplayServer"] == "wayland"
    # SDDM ignores unknown keys silently; CompositorCommand under [General]
    # is one of them.
    assert "CompositorCommand" not in cp["General"]
    assert cp["Wayland"]["CompositorCommand"].startswith("kwin_wayland ")
    assert cp["Autologin"]["User"] == "liveuser"


def test_the_mtime_unit_runs_before_every_kde_display_manager():
    u = unit()
    before = u["Unit"]["Before"].split()
    for dm in ("display-manager.service", "sddm.service", "plasmalogin.service"):
        assert dm in before
    text = ADAPTER.read_text(encoding="utf-8")
    assert "for _dm_unit in display-manager.service sddm.service plasmalogin.service" in text
    assert '"/etc/systemd/system/${_dm_unit}.wants/tunaos-live-dm-config.service"' in text


def test_the_exec_line_escapes_dollar_for_systemd():
    exec_start = unit()["Service"]["ExecStart"]
    # systemd expands $VAR in ExecStart; only $$ survives as a literal $.
    assert "$d" not in exec_start.replace("$$d", "")


def run_exec_start(tmp_path: Path) -> None:
    exec_start = unit()["Service"]["ExecStart"]
    # Undo systemd's escaping and point the absolute paths at a scratch root.
    cmd = exec_start.replace("$$", "$").replace("/etc/", f"{tmp_path}/etc/")
    m = re.fullmatch(r"/bin/sh -c '(.*)'", cmd)
    assert m, cmd
    subprocess.run(["sh", "-c", m.group(1)], check=True, timeout=30)


def test_the_unit_gives_zero_mtimes_a_real_time(tmp_path):
    d = tmp_path / "etc" / "sddm.conf.d"
    d.mkdir(parents=True)
    f = d / "live-autologin.conf"
    f.write_text("[General]\n")
    for p in (f, d):
        os.utime(p, (0, 0))
    run_exec_start(tmp_path)
    assert d.stat().st_mtime > 0
    assert f.stat().st_mtime > 0


def test_the_unit_creates_nothing(tmp_path):
    # An empty or missing directory must not grow a file literally named '*'.
    empty = tmp_path / "etc" / "plasmalogin.conf.d"
    empty.mkdir(parents=True)
    run_exec_start(tmp_path)
    assert list(empty.iterdir()) == []
    assert not (tmp_path / "etc" / "sddm.conf.d").exists()
