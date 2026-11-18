"""tunaOS#4459: an installed SDDM with no X server must still draw a greeter.

What shipped: grouper:kde (Ubuntu 26.04) installs boot to the text console
and never show a login screen. SDDM's built-in default is DisplayServer=x11,
Ubuntu's sddm package ships no Wayland drop-in, and the image has no X
server. The live ISO had its own config; the installed system had none.
Measured in iso-builder strict diag run 43547709594: 60 first-boot frames of
boot log on the plain leg and 21 on the luks leg, no greeter, while
e2e-runtime-checks reported sddm.service active.

What the test holds: build_scripts/desktop/kde-sddm-wayland.sh, run against a
scratch root with no X server on PATH, writes a drop-in SDDM reads as
DisplayServer=wayland with the compositor under [Wayland], enables a unit
ordered before sddm, and that unit's own ExecStart gives zero-mtime drop-ins
a real time (SDDM ignores config whose newest mtime is 0). With an X server
on PATH it writes nothing.

Falsification: behavioural. The tests run the real helper. Remove the drop-in
or move CompositorCommand under [General] and the config assertions fail;
drop the `systemctl enable` and the enablement assertion fails; break the
ExecStart escaping and the zero-mtime file keeps mtime 0.
"""

from __future__ import annotations

import configparser
import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "build_scripts" / "desktop" / "kde-sddm-wayland.sh"


def stub_path(tmp_path: Path, with_x: bool) -> tuple[str, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "systemctl.log"
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    systemctl.chmod(systemctl.stat().st_mode | stat.S_IEXEC)
    if with_x:
        xorg = bin_dir / "Xorg"
        xorg.write_text("#!/bin/sh\nexit 0\n")
        xorg.chmod(xorg.stat().st_mode | stat.S_IEXEC)
    # Only the stubs and the coreutils the helper needs; no host X server.
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("bash", "sh", "mkdir", "cat"):
        for d in ("/usr/bin", "/bin"):
            if os.path.exists(f"{d}/{name}"):
                (tools / name).symlink_to(f"{d}/{name}")
                break
    return f"{bin_dir}:{tools}", log


def run_helper(tmp_path: Path, with_x: bool) -> tuple[Path, Path, str]:
    root = tmp_path / "root"
    root.mkdir()
    path, log = stub_path(tmp_path, with_x)
    env = {"PATH": path, "TUNAOS_DM_ROOT": str(root)}
    out = subprocess.run([str(tools_bash(tmp_path)), str(HELPER)], env=env, check=True,
                         capture_output=True, text=True, timeout=30)
    return root, log, out.stdout


def tools_bash(tmp_path: Path) -> Path:
    return tmp_path / "tools" / "bash"


def ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read_string(path.read_text())
    return cp


def test_no_x_server_gets_a_wayland_greeter(tmp_path):
    root, log, _ = run_helper(tmp_path, with_x=False)
    conf = ini(root / "etc" / "sddm.conf.d" / "10-tunaos-wayland.conf")
    assert conf["General"]["DisplayServer"] == "wayland"
    # SDDM drops unknown keys silently; CompositorCommand under [General] is one.
    assert "CompositorCommand" not in conf["General"]
    assert conf["Wayland"]["CompositorCommand"].startswith("kwin_wayland --drm ")
    unit = ini(root / "usr" / "lib" / "systemd" / "system" / "tunaos-sddm-config-mtime.service")
    assert "sddm.service" in unit["Unit"]["Before"].split()
    assert unit["Install"]["WantedBy"] == "sddm.service"
    assert f"--root={root} enable tunaos-sddm-config-mtime.service" in log.read_text()


def test_the_unit_gives_zero_mtime_drop_ins_a_real_time(tmp_path):
    root, _, _ = run_helper(tmp_path, with_x=False)
    unit = ini(root / "usr" / "lib" / "systemd" / "system" / "tunaos-sddm-config-mtime.service")
    exec_start = unit["Service"]["ExecStart"]
    conf_d = root / "etc" / "sddm.conf.d"
    for p in (conf_d, *conf_d.iterdir()):
        os.utime(p, (0, 0))
    cmd = exec_start.replace("$$", "$").replace("/etc/", f"{root}/etc/")
    m = re.fullmatch(r"/bin/sh -c '(.*)'", cmd)
    assert m, cmd
    subprocess.run(["sh", "-c", m.group(1)], check=True, timeout=30)
    assert conf_d.stat().st_mtime > 0
    assert all(p.stat().st_mtime > 0 for p in conf_d.iterdir())


def test_an_installed_x_server_is_left_alone(tmp_path):
    root, log, out = run_helper(tmp_path, with_x=True)
    assert not (root / "etc" / "sddm.conf.d").exists()
    assert not log.exists()
    assert "leaving SDDM" in out
