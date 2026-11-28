"""Contract for the EL10 soft-reboot probe (tunaOS#4909 spike)."""

import os
import subprocess
from pathlib import Path

PROBE = Path(__file__).resolve().parent.parent / "installer-medium/hooks/el10-soft-reboot-probe"


def run(tmp_path, cmdline, *, modules=True, init=True, help_text="soft-reboot"):
    root = tmp_path / "root"
    if modules:
        (root / "usr/lib/modules" / os.uname().release).mkdir(parents=True)
    if init:
        sd = root / "usr/lib/systemd"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "systemd").write_text("#!/bin/sh\n")
        (sd / "systemd").chmod(0o755)
    root.mkdir(exist_ok=True)
    cl = tmp_path / "cmdline"
    cl.write_text(cmdline)
    env = {**os.environ, "PROBE_CMDLINE": str(cl), "PROBE_SYSTEMCTL_HELP": help_text,
           "PROBE_KEXEC_SYSCTL": str(tmp_path / "none")}
    return subprocess.run([str(PROBE), str(root)], env=env, capture_output=True, text=True)


def test_viable_root_soft_reboots(tmp_path):
    r = run(tmp_path, "quiet rhgb")
    assert r.returncode == 0
    assert "verdict=soft-reboot" in r.stdout


def test_live_args_are_reported(tmp_path):
    r = run(tmp_path, "quiet utah.live=1 rd.live.image root=live:LABEL=x")
    assert "cmdline_needs_ignore_rule=1" in r.stdout
    assert "utah.live=1" in r.stdout


def test_missing_kernel_modules_fall_back(tmp_path):
    r = run(tmp_path, "quiet", modules=False)
    assert r.returncode == 10
    assert "verdict=normal-reboot" in r.stdout


def test_old_systemctl_falls_back(tmp_path):
    r = run(tmp_path, "quiet", help_text="reboot poweroff")
    assert r.returncode == 10


def test_no_target_is_usage_error(tmp_path):
    r = subprocess.run([str(PROBE)], capture_output=True, text=True)
    assert r.returncode == 2
