"""XFCE strict qualification: installer identity step, greeter login, wiring.

scripts/lib/xfce_installer_driver.py drives the bundled InstallerXfce wizard,
whose identity step creates the installed system's user;
scripts/lib/xfce_first_boot.py proves the greeter offers that account
and its password opens the user's session. These inert tests replay OCR
frames through both: no guest, no VNC, no OCR binaries.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import xfce_first_boot as fb
from lib import xfce_installer_driver as xd

SOURCE = (ROOT / "scripts/iso-e2e.sh").read_text()
USER, PASSWORD, LUKS = "tunaose2e", "harbor-sunset-4817", "tunaos-e2e-luks"


class FakeScreen:
    width, height = 1280, 800

    def __init__(self, lines, rows=None):
        self.lines = list(lines)
        if rows is not None:
            self.rows = list(rows)
        else:
            self.rows = [(line, (100, 50 + 30 * i, 300, 75 + 30 * i)) for i, line in enumerate(lines)]
        self.state = fb.classify(self.lines)

    def contains(self, text):
        return any(xd.normal(text) in xd.normal(line) for line in self.lines)

    def box(self, label):
        boxes = [box for text, box in self.rows if xd.normal(text) == xd.normal(label)
                 or (label == 'No encryption' and xd.normal(text) == 'o no encryption')]
        if not boxes:
            boxes = [box for text, box in self.rows if xd.normal(label) in xd.normal(text)]
        if len(boxes) != 1:
            raise xd.Unverified('GUI control missing or ambiguous: ' + label)
        return boxes[0]

    def has(self, label):
        return any(xd.normal(label) in xd.normal(line) for line in self.lines)

    def summary(self, label):
        anchor = self.box(label + ':')
        center = (anchor[1] + anchor[3]) / 2
        rows = [text for text, box in self.rows if box[0] > anchor[2] and abs((box[1] + box[3]) / 2 - center) < 8]
        if len(rows) != 1:
            raise xd.Unverified('summary value absent or ambiguous: ' + label)
        return rows[0]

    def entry(self, label, labels):
        boxes = [self.box(item) for item in labels]
        box = self.box(label)
        return max(b[2] for b in boxes) + 35, (box[1] + box[3]) // 2


WELCOME = ["Install TunaOS", "Get started"]
SOURCE_PAGE = ["What do you want to install?", "TunaOS Flounder (this system)", "available offline", "Next"]
DEST_PAGE = ["Where should TunaOS be installed?", "/dev/vda will be erased", "/dev/vda", "Next"]
ENC_PAGE_PLAIN = ["Disk encryption", "No encryption", "Passphrase", "Next"]
ENC_PAGE_LUKS = ["Disk encryption", "No encryption", "Passphrase", "Confirm", "Next"]
IDENTITY_PAGE = ["Name this computer", "Hostname", "Your account", "Username", "Full name", "Password", "Next"]


def make_confirm_page(encryption="No encryption", user=USER, hostname="tuna-candidate", disk="/dev/vda"):
    # rows layout: anchor label at x=100..200, summary value at x=250..400 at same y
    lines = ["Confirm installation", f"Everything on {disk} will be erased",
             "Target disk:", disk, "Hostname:", hostname, "User:", user,
             "Image:", "TunaOS Flounder", "Filesystem:", "btrfs", "Encryption:", encryption,
             "Install"]
    rows = [
        ("Confirm installation", (100, 10, 400, 30)),
        (f"Everything on {disk} will be erased", (100, 40, 500, 60)),
        ("Target disk:", (100, 70, 200, 90)), (disk, (250, 70, 400, 90)),
        ("Hostname:", (100, 100, 200, 120)), (hostname, (250, 100, 400, 120)),
        ("User:", (100, 130, 200, 150)), (user, (250, 130, 400, 150)),
        ("Image:", (100, 160, 200, 180)), ("TunaOS Flounder", (250, 160, 400, 180)),
        ("Filesystem:", (100, 190, 200, 210)), ("btrfs", (250, 190, 400, 210)),
        ("Encryption:", (100, 220, 200, 240)), (encryption, (250, 220, 400, 240)),
        ("Install", (300, 260, 380, 290)),
    ]
    return FakeScreen(lines, rows)


PROGRESS_PAGE = ["Do not power off", "Installing TunaOS…", "Next"]
DONE_PAGE = ["TunaOS is installed", "Remove the installation media and restart", "Restart now"]


def run_install(mode, tmp_path, confirm_screen=None):
    confirm_screen = confirm_screen or make_confirm_page("Passphrase" if mode == "luks" else "No encryption")
    enc_page = ENC_PAGE_LUKS if mode == "luks" else ENC_PAGE_PLAIN
    screens = [
        FakeScreen(WELCOME),
        FakeScreen(SOURCE_PAGE),
        FakeScreen(DEST_PAGE),
        FakeScreen(enc_page),
    ]
    if mode == "luks":
        screens.append(FakeScreen(enc_page))
        screens.append(FakeScreen(enc_page))
    else:
        screens.append(FakeScreen(enc_page))
    screens.extend([
        FakeScreen(IDENTITY_PAGE),
        FakeScreen(IDENTITY_PAGE),
        confirm_screen,
        FakeScreen(PROGRESS_PAGE),
        FakeScreen(DONE_PAGE),
    ])
    frames = iter(screens)
    shown = {}
    typed, keys_pressed, clicks = [], [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    def pointer(vnc, x, y, width, height, click=True):
        clicks.append((x, y))
        return True

    result = xd.drive(
        tmp_path, mode, "vnc", capture, keys_pressed.append, typed.append,
        "sha256:" + "a" * 64, LUKS, USER, PASSWORD,
        screen_factory=lambda path: shown[path],
        pointer=pointer, sleep=lambda s: None, clock=lambda: 0.0,
    )
    evidence = json.loads((tmp_path / "walkthrough-xfce.json").read_text())
    return result, evidence, typed


@pytest.mark.parametrize("mode", ["plain", "luks"])
def test_xfce_installer_creates_account_and_completes(tmp_path, mode):
    result, evidence, typed = run_install(mode, tmp_path)
    assert result == 0
    assert evidence["completed"] and evidence["submitted"] and evidence["accepted"]
    assert evidence["transitions"] == ["welcome", "source", "destination", "setup", "identity", "confirm", "progress", "done"]
    # Password and LUKS secret never serialized
    raw = json.dumps(evidence)
    assert PASSWORD not in raw and LUKS not in raw


def test_xfce_installer_confirm_mismatch_fails(tmp_path):
    bad_confirm = make_confirm_page("No encryption", user="otheruser")
    with pytest.raises(xd.Unverified, match="summary identity mismatch"):
        run_install("plain", tmp_path, confirm_screen=bad_confirm)
    evidence = json.loads((tmp_path / "walkthrough-xfce.json").read_text())
    assert evidence["submitted"] is False


def test_xfce_installer_failure_screen_fails(tmp_path):
    fail_screen = FakeScreen(["Installation failed", "Something went wrong"])
    screens = [FakeScreen(WELCOME), FakeScreen(SOURCE_PAGE), fail_screen]
    frames = iter(screens)
    shown = {}

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    with pytest.raises(xd.Unverified, match="reports failure"):
        xd.drive(
            tmp_path, "plain", "vnc", capture,
            lambda k: None, lambda t: None, "sha256:" + "a" * 64, LUKS, USER, PASSWORD,
            screen_factory=lambda path: shown[path],
            pointer=lambda *a, **k: True,
            sleep=lambda s: None, clock=lambda: 0.0,
        )


GREETER_LIGHTDM = [USER, "Password", "Log In", "Session"]
GREETER_GTKGREET = ["gtkgreet", "login:", "Password:", "gtkgreet"]
LAUNCHER_XFCE = ["Applications", "Settings", "System", "Log Out", "Terminal Emulator"]


@pytest.mark.parametrize("lines,state", [
    (GREETER_LIGHTDM, "greeter"),
    (GREETER_GTKGREET, "greeter"),
    (LAUNCHER_XFCE, "session-launcher"),
    (["login failed", "incorrect password"], "login-failed"),
    (["some random text"], "unknown"),
])
def test_xfce_first_boot_classify(lines, state):
    assert fb.classify(lines) == state


def run_first_boot(phase, screens, tmp_path):
    frames = iter(screens)
    shown = {}
    typed, keys_pressed, clicks = [], [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    def pointer(vnc, x, y, width, height, click=True):
        clicks.append((x, y))
        return True

    result = fb.drive(
        tmp_path, phase, "vnc", capture, keys_pressed.append, typed.append,
        USER, PASSWORD,
        screen_factory=lambda path: shown[path],
        pointer=pointer, sleep=lambda s: None, clock=lambda: 0.0,
    )
    evidence = json.loads((tmp_path / f"first-boot-{phase}.json").read_text())
    return result, evidence, typed, keys_pressed


@pytest.mark.parametrize("phase", ["setup", "login"])
def test_xfce_first_boot_completes(tmp_path, phase):
    screens = [FakeScreen(GREETER_LIGHTDM), FakeScreen(LAUNCHER_XFCE)]
    result, evidence, typed, keys = run_first_boot(phase, screens, tmp_path)
    assert result == 0
    assert evidence["completed"] is True
    assert evidence["greeter_offers_account"] is True
    assert evidence["session_user_observed"] is True
    assert typed == [PASSWORD]
    assert "ret" in keys
    # Secret never leaked
    assert PASSWORD not in json.dumps(evidence)


def test_xfce_first_boot_login_failure_fails(tmp_path):
    screens = [FakeScreen(GREETER_LIGHTDM), FakeScreen(["login failed", "incorrect password"])]
    result, evidence, _, _ = run_first_boot("login", screens, tmp_path)
    assert result == 1
    assert evidence["completed"] is False
    assert "rejected" in evidence.get("error", "")


def function(name):
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize("flavor,candidate,required", [
    ("gnome", "0", True),
    ("xfce", "0", True),
    ("kde", "0", False),
    ("xfce", "1", False),
])
def test_strict_first_boot_required_scope(flavor, candidate, required):
    result = subprocess.run(
        ["bash", "-c", function("strict_first_boot_required") + 'strict_first_boot_required plain'],
        env={"FLAVOR": flavor, "TUNAOS_XFCE_CANDIDATE": candidate, "PATH": "/usr/bin:/bin"},
        capture_output=True, check=False, timeout=5,
    )
    assert (result.returncode == 0) is required


def test_strict_first_boot_gui_passes_xfce_flavor(tmp_path):
    harness = function("strict_first_boot_gui") + """
e2e_phase() { :; }
python3() { echo "$*" >"$OUTPUT_DIR/argv"; return 0; }
strict_poweroff_installed() { :; }
strict_offline_evidence() { :; }
strict_first_boot_gui plain login
"""
    env = {
        "OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": "/s", "SERIAL_LOG": str(tmp_path / "serial"),
        "MONITOR_SOCK": "/m", "E2E_INSTALL_USER": USER, "FLAVOR": "xfce", "PATH": "/usr/bin:/bin",
    }
    subprocess.run(["bash", "-c", harness], env=env, check=True, timeout=5)
    argv = (tmp_path / "argv").read_text().split()
    assert argv[4] == "xfce" and "--first-boot=login" in argv
