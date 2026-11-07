"""Pantheon strict qualification: installer driving, LightDM greeter login, wiring.

scripts/lib/gnome_installer_driver.py drives the GTK4 bootc-installer frontend on
Pantheon (desktop-pantheon.sh launches org.bootcinstaller.Installer under Gala).
scripts/lib/pantheon_first_boot.py tests io.elementary.greeter on LightDM.
These inert tests replay OCR frames through both: no guest, no VNC, no OCR binaries.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from lib import gnome_installer_driver as gd
from lib import pantheon_first_boot as pb
from test_gnome_installer_driver import FakeScreen as GnomeFakeScreen

SOURCE = (ROOT / "scripts/iso-e2e.sh").read_text()
USER, PASSWORD, LUKS = "tunaose2e", "harbor-sunset-4817", "tunaos-e2e-luks"


class FakeScreen:
    width, height = 1280, 800

    def __init__(self, lines, classify_fn=pb.classify):
        self.lines = list(lines)
        self.rows = [(line, (400, 100 + 30 * i, 600, 120 + 30 * i)) for i, line in enumerate(lines)]
        self.state = classify_fn(self.lines)

    def has(self, text):
        from lib.gnome_installer_driver import normal
        target = normal(text)
        return any(normal(line) == target or target in normal(line) for line in self.lines)


# ── Installer driving for Pantheon ──────────────────────────────────────────

def test_pantheon_installer_driver_evidence_and_receipt(tmp_path):
    """The installer driver writes walkthrough-pantheon.json and names pantheon driver."""
    screens = [
        GnomeFakeScreen('welcome', product='Gurnard'),
        GnomeFakeScreen('encryption', encrypted=True, product='Gurnard'),
        GnomeFakeScreen('encryption', product='Gurnard'),
        GnomeFakeScreen('summary', product='Gurnard'),
        GnomeFakeScreen('progress', product='Gurnard'),
        GnomeFakeScreen('done', product='Gurnard'),
    ]

    events = []
    def pointer(*args):
        events.append(('click', args))
        return True

    def capture(idx, label, directory=None):
        path = Path(directory or tmp_path) / f'{idx}.png'
        path.write_bytes(b'inert captured frame')
        return str(path)

    def factory(path):
        if not screens:
            raise gd.Unverified('fixture exhausted')
        return screens.pop(0)

    rc = gd.drive(
        str(tmp_path), "plain", tmp_path / "vnc.sock", capture,
        lambda *k: events.append(('key', k)),
        lambda p: events.append(('type', len(p))),
        gd.BUNDLE_DIGEST, LUKS, "tuna-os/skipjack:gnome",
        screen_factory=factory, pointer=pointer, sleep=lambda _: None,
        clock=lambda: 0.0, flavor="pantheon"
    )

    report_path = tmp_path / "walkthrough-pantheon.json"
    assert report_path.exists(), "walkthrough-pantheon.json must be written"
    evidence = json.loads(report_path.read_text())
    assert evidence["driver"] == "pantheon-23e47c51"
    assert evidence["mode"] == "plain"
    assert evidence["completed"] is True
    assert rc == 0


# ── Greeter and First Boot for Pantheon ─────────────────────────────────────

GREETER_WITH_ACCOUNT = [USER, "Password", "Log In", "elementary OS", "Pantheon"]
GREETER_WITHOUT_ACCOUNT = ["Password", "Log In", "elementary OS"]
SESSION_LAUNCHER = ["Applications", "Search…", "System Settings", "Terminal"]


def run_login(phase, frames, tmp_path, user=USER):
    frames_iter = iter(frames)
    shown, typed, keys = {}, [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames_iter)
        return path

    result = pb.drive(
        str(tmp_path), phase, "vnc", capture, keys.append, typed.append, user, PASSWORD,
        screen_factory=lambda path: FakeScreen(shown[path], pb.classify),
        pointer=lambda *a, **k: True, sleep=lambda s: None, clock=lambda: 0.0
    )
    evidence = json.loads((tmp_path / f"first-boot-{phase}.json").read_text())
    return result, evidence, typed, keys


@pytest.mark.parametrize("phase", ["setup", "login"])
def test_pantheon_greeter_login_opens_session(tmp_path, phase):
    result, evidence, typed, keys = run_login(phase, [GREETER_WITH_ACCOUNT, SESSION_LAUNCHER], tmp_path)
    assert result == 0 and evidence["completed"] and evidence["session_user_observed"]
    assert typed == [PASSWORD] and "ret" in keys


def test_pantheon_greeter_without_the_account_fails_closed(tmp_path):
    """When no user account exists (the installer created none and no initial setup ran), greeter fails."""
    result, evidence, typed, _ = run_login("setup", [GREETER_WITHOUT_ACCOUNT], tmp_path)
    assert result == 1 and not evidence["completed"]
    assert "greeter does not offer the expected account" in evidence["error"]
    assert typed == []


def test_pantheon_greeter_rejected_password_fails_closed(tmp_path):
    failed_frame = ["Incorrect password", "Password", "Log In"]
    result, evidence, _, _ = run_login("login", [GREETER_WITH_ACCOUNT, failed_frame], tmp_path)
    assert result == 1 and not evidence["completed"]
    assert "rejected" in evidence["error"]


# ── Wiring and contract in iso-e2e.sh ───────────────────────────────────────

def function(name):
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize("flavor,required", [("pantheon", True), ("gnome", True), ("xfce", False), ("cosmic", False)])
def test_first_boot_scope_includes_pantheon(flavor, required):
    result = subprocess.run(
        ["bash", "-c", function("strict_first_boot_required") + 'strict_first_boot_required plain'],
        env={"FLAVOR": flavor, "TUNAOS_XFCE_CANDIDATE": "0", "PATH": "/usr/bin:/bin"},
        capture_output=True, check=False, timeout=5)
    assert (result.returncode == 0) is required


def test_first_boot_gui_passes_pantheon_flavor(tmp_path):
    harness = function("strict_first_boot_gui") + """
e2e_phase() { :; }
python3() { echo "$*" >"$OUTPUT_DIR/argv"; return 0; }
strict_poweroff_installed() { :; }
strict_offline_evidence() { :; }
strict_first_boot_gui luks login
"""
    env = {"OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": "/s", "SERIAL_LOG": str(tmp_path / "serial"),
           "MONITOR_SOCK": "/m", "E2E_INSTALL_USER": USER, "FLAVOR": "pantheon", "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", "-c", harness], env=env, check=True, timeout=5)
    argv = (tmp_path / "argv").read_text().split()
    assert argv[4] == "pantheon" and "--first-boot=login" in argv
