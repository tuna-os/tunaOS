"""XFCE starts Orca from the screen reader setting (A6 of the installer standard).

Orca's autostart entry is OnlyShowIn=GNOME;MATE;Unity;Cinnamon; and
xfce4-session ignores AutostartCondition, so the XFCE experience ships its
own entry and wrapper. These tests run the wrapper with stand-ins.
"""

import configparser
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

FILES = Path(__file__).parents[1] / "experiences" / "xfce" / "files"
WRAPPER = FILES / "usr/libexec/tunaos/xfce-screen-reader"
ENTRY = FILES / "etc/xdg/autostart/tunaos-xfce-screen-reader.desktop"


def stub(bindir, name, body):
    path = bindir / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def run(tmp_path, key, orca=True, first=False, before=None):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "log"
    stub(bindir, "gsettings", f'echo "gsettings $*" >>{log}\necho {key}\n')
    if orca:
        stub(bindir, "orca", f'echo "orca $*" >>{log}\n')
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    autostart = tmp_path / "first.desktop"
    if first:
        autostart.write_text("[Desktop Entry]\n", encoding="utf-8")
    sleep = bindir / "sleep"
    if not sleep.exists():
        sleep.symlink_to(shutil.which("sleep"))
    # Only the stand-ins: a host Orca must not run.
    env = {"PATH": str(bindir), "HOME": str(home),
           "TUNAOS_FIRST_LOGIN_AUTOSTART": str(autostart)}
    if before:
        before(home)
    start = time.monotonic()
    subprocess.run([str(WRAPPER)], env=env, check=True, timeout=30)
    return (log.read_text(encoding="utf-8") if log.exists() else ""), time.monotonic() - start


def test_the_entry_runs_the_wrapper_in_xfce_only():
    entry = configparser.ConfigParser(interpolation=None)
    entry.optionxform = str
    entry.read(ENTRY, encoding="utf-8")
    section = entry["Desktop Entry"]
    assert section["Exec"] == "/usr/libexec/tunaos/xfce-screen-reader"
    assert section["OnlyShowIn"] == "XFCE;"
    assert section["TryExec"] == "orca"
    assert os.access(WRAPPER, os.X_OK)


def test_the_setting_on_starts_orca(tmp_path):
    log, _ = run(tmp_path, "true")
    assert "orca --replace" in log


def test_the_setting_off_starts_nothing(tmp_path):
    log, _ = run(tmp_path, "false")
    assert "orca" not in log


def test_no_orca_is_no_failure(tmp_path):
    log, _ = run(tmp_path, "true", orca=False)
    assert "orca" not in log


def test_it_waits_for_the_installers_first_login_script(tmp_path):
    def later(home):
        marker = home / ".local/state/tunaos/first-login-accessibility.done"

        def write():
            time.sleep(2)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        threading.Thread(target=write, daemon=True).start()

    log, took = run(tmp_path, "true", first=True, before=later)
    assert "orca --replace" in log
    assert 1.5 < took < 10


def test_a_done_first_login_does_not_wait(tmp_path):
    def done(home):
        path = home / ".local/state/tunaos/first-login-accessibility.done"
        path.parent.mkdir(parents=True)
        path.touch()

    _, took = run(tmp_path, "false", first=True, before=done)
    assert took < 1.5
