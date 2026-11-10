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
    """OCR lines at stacked boxes; a line prefixed '*' was read inside an
    accent fill (an enabled suggested action or the selected row)."""
    width, height = 1280, 800

    def __init__(self, lines, classify_fn=pb.classify):
        self.rows, self.accent_rows = [], []
        for i, line in enumerate(lines):
            row = (line.lstrip('*'), (400, 100 + 30 * i, 600, 120 + 30 * i))
            self.rows.append(row)
            if line.startswith('*'):
                self.accent_rows.append(row)
        self.lines = [text for text, _ in self.rows]
        self.state = classify_fn(self.lines)

    box = pb.Screen.box
    count = pb.Screen.count
    has = pb.Screen.has


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


# ── Initial Setup, greeter and session for Pantheon ─────────────────────────

# Page text from io.elementary.initial-setup 8.0.1 (src/Views/*.vala).
LANGUAGE = ["Select a Language", "*English…", "Chinese…", "Spanish", "French…", "Russian", "German…", "*Select"]
LANGUAGE_COUNTRIES = ["Select a Language", "Languages", "English…", "Australia", "Canada",
                      "United Kingdom", "*United States", "*Select"]
KEYBOARD = ["Select Keyboard Layout", "English (UK)…", "*English (US)…", "Type to test your layout",
            "Back", "*Select"]
KEYBOARD_VARIANTS = ["Select Keyboard Layout", "Input Language", "English (US)", "*Default",
                     "Cherokee", "Type to test your layout", "Back", "*Select"]
NETWORK = ["Connect Network", "Connect a network cable", "Back", "*Skip"]
ACCOUNT = ["Create an Account", "Full Name", "Username", "Choose a Password", "Confirm Password",
           "Device name", "Back", "Finish Setup"]
ACCOUNT_NAMED = ["Create an Account", "Full Name", USER, "Username", USER, "Choose a Password",
                 "Confirm Password", "Device name", "Back", "Finish Setup"]
ACCOUNT_READY = ACCOUNT_NAMED[:-1] + ["*Finish Setup"]
INITIAL_SETUP = [LANGUAGE, LANGUAGE_COUNTRIES, KEYBOARD, KEYBOARD_VARIANTS, NETWORK, ACCOUNT,
                 ACCOUNT_NAMED, ACCOUNT_READY]
GREETER_WITH_ACCOUNT = [USER, "Password", "Log In", "elementary OS", "Pantheon"]
GREETER_WITHOUT_ACCOUNT = ["Password", "Log In", "elementary OS"]
# io.elementary.terminal opened by the media-keys terminal binding.
SESSION_TERMINAL = ["Terminal", f"{USER}@gurnard:~$"]


def run_login(phase, frames, tmp_path, user=USER):
    frames_iter = iter(frames)
    shown, typed, keys = {}, [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames_iter)
        return path

    result = pb.drive(
        str(tmp_path), phase, "vnc", capture, lambda *k: keys.extend(k),
        typed.append, user, PASSWORD,
        screen_factory=lambda path: FakeScreen(shown[path], pb.classify),
        pointer=lambda *a, **k: True, sleep=lambda s: None, clock=lambda: 0.0
    )
    evidence = json.loads((tmp_path / f"first-boot-{phase}.json").read_text())
    return result, evidence, typed, keys


def test_pantheon_initial_setup_creates_the_account_and_logs_in(tmp_path):
    frames = INITIAL_SETUP + [GREETER_WITH_ACCOUNT, SESSION_TERMINAL]
    result, evidence, typed, _ = run_login("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] and evidence["session_user_observed"]
    assert evidence["pages"] == ["setup-language", "setup-keyboard", "setup-network", "setup-account"]
    assert [c["label"] for c in evidence["clicks"]] == ["English", "Select", "Select", "Select", "Skip",
                                                         "Finish Setup"]
    # Full Name, then password and confirmation at Initial Setup, then the greeter.
    assert typed == [USER, PASSWORD, PASSWORD, PASSWORD]
    assert evidence["account_name_observed"] and evidence["account_submitted"]
    # The password frame is private: no transcript of it is kept.
    assert any(f.get("private") for f in evidence["frames"])


def test_pantheon_login_opens_session(tmp_path):
    result, evidence, typed, keys = run_login("login", [GREETER_WITH_ACCOUNT, SESSION_TERMINAL], tmp_path)
    assert result == 0 and evidence["completed"] and evidence["session_user_observed"]
    assert typed == [PASSWORD] and keys == ["ret", "meta_l-t"]


def test_pantheon_session_of_another_account_fails_closed(tmp_path):
    """A prompt for any other user is not this account's session."""
    other = ["Terminal", "liveuser@gurnard:~$"]
    result, evidence, _, _ = run_login("login", [GREETER_WITH_ACCOUNT] + [other] * 12, tmp_path)
    assert result == 1 and not evidence["completed"]
    assert "no terminal prompt of the account" in evidence["error"]


def test_pantheon_setup_refuses_an_account_that_existed_before_initial_setup(tmp_path):
    result, evidence, typed, _ = run_login("setup", [GREETER_WITH_ACCOUNT], tmp_path)
    assert result == 1 and "before Initial Setup" in evidence["error"]
    assert typed == []


def test_pantheon_setup_fails_closed_when_initial_setup_cannot_launch(tmp_path):
    """The greeter's own error when the image lacks io.elementary.initial-setup."""
    error = ["Unable to Launch Initial Setup",
             "Initial Setup creates your first user. Without it, you will not be able to log in"]
    result, evidence, typed, _ = run_login("setup", [error], tmp_path)
    assert result == 1 and "cannot create the account" in evidence["error"]
    assert typed == []


def test_pantheon_setup_refuses_a_name_typed_into_the_wrong_field(tmp_path):
    """Only one entry shows the name: it did not land in Full Name (which fills Username)."""
    one_read = ["Create an Account", "Full Name", "Username", USER, "Choose a Password",
                "Confirm Password", "Finish Setup"]
    frames = INITIAL_SETUP[:6] + [one_read] * 6
    result, evidence, typed, _ = run_login("setup", frames, tmp_path)
    assert result == 1 and not evidence.get("account_submitted")
    assert typed == [USER]


def test_pantheon_setup_never_clicks_a_disabled_finish(tmp_path):
    frames = INITIAL_SETUP[:7] + [ACCOUNT_NAMED]
    result, evidence, _, _ = run_login("setup", frames, tmp_path)
    assert result == 1 and "Finish Setup" in evidence["error"]
    assert "Finish Setup" not in [c["label"] for c in evidence["clicks"]]


def test_pantheon_login_without_the_account_fails_closed(tmp_path):
    result, evidence, typed, _ = run_login("login", [GREETER_WITHOUT_ACCOUNT], tmp_path)
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


@pytest.mark.parametrize("flavor,required", [("pantheon", True), ("gnome", True), ("xfce", True), ("cosmic", True), ("niri", True), ("lxqt", False)])
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
