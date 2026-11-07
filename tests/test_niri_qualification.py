"""Niri strict qualification: installer account step, greeter login, wiring.

scripts/lib/niri_installer_driver.py drives the bundled InstallerNiri wizard
(tuna-os/bootc-installer frontends/niri/ui/installer.qml), whose account step
creates the installed system's user; scripts/lib/niri_first_boot.py proves the
greetd greeter accepts that account and a niri session opens. These inert
tests replay OCR rows through both: no guest, no VNC, no OCR binaries. The
rows are the QML's own strings, including the top bar and the hint bar.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import niri_first_boot as fb
from lib import niri_installer_driver as nd

SOURCE = (ROOT / "scripts/iso-e2e.sh").read_text()
USER, PASSWORD, LUKS = "tunaose2e", "harbor-sunset-4817", "tunaos-e2e-luks"
HINT = [("Enter", 40), ("Continue", 90), ("Shift+Enter", 170), ("Back", 260), ("Tab", 320), ("Next field", 380)]


class FakeScreen:
    width, height = 1280, 800

    def __init__(self, rows, classify):
        # rows: (text, x) pairs laid out top to bottom.
        self.rows = [(text, (x, 40 + 30 * i, x + 8 * max(len(text), 2), 58 + 30 * i))
                     for i, (text, x) in enumerate(rows)]
        self.lines = [text for text, _ in self.rows]
        self.state = classify(self.lines)

    matching = nd.Screen.matching
    boxes = nd.Screen.boxes
    box = nd.Screen.box
    button = nd.Screen.button
    has = nd.Screen.has
    contains = nd.Screen.contains
    value_right = nd.Screen.value_right


def page(step, name, body, hint=True, hint_action="Continue"):
    rows = [(f"Step {step} of 9 · {name}", 40)] + [(t, x) for t, x in body]
    if hint:
        rows += [(t if t != "Continue" else hint_action, x) for t, x in HINT]
    return rows


def buttons(primary="Continue", back=True):
    return ([("Back", 60)] if back else []) + [(primary, 1100)]


def welcome(product="Marlin"):
    return page(1, "Welcome", [(f"Welcome to {product}", 520),
                               ("Install this system — no download required.", 480),
                               ("Get started", 600)])


SESSION = page(2, "Session", [("Session", 60), ("Keyboard and language", 60), ("Keyboard", 80),
                              ("Network", 60), ("Offline — only installed or cached images can be used.", 80)]
               + buttons())
SOURCE_PAGE = page(3, "Source", [("What do you want to install?", 60), ("Install Marlin", 80),
                                 ("Installs to your internal disk.", 80)] + buttons())


def disk(selected):
    target = "/dev/vda" if selected else "the selected disk"
    return page(4, "Disk", [("Destination", 60), (f"Everything on {target} will be erased. This cannot be undone.", 60),
                            ("QEMU HARDDISK", 80), ("/dev/vda · 64 GiB · VirtIO", 80)] + buttons())


def enc(passphrase):
    body = [("Disk encryption", 60),
            ("Encryption protects your files if the disk is lost or stolen. It cannot be turned on later without reinstalling.", 60),
            ("No encryption", 80), ("Anyone with the disk can read your files.", 80),
            ("Passphrase", 80), ("You'll type it at every boot.", 80),
            ("TPM + passphrase", 80)]
    if passphrase:
        body += [("Passphrase", 80), ("Enter passphrase", 100), ("Confirm passphrase", 100)]
    return page(5, "Encryption", body + [("Advanced", 60), ("Filesystem", 80)] + buttons())


def account(typed=False):
    body = [("Your account", 60), ("The account you sign in with. It can administer this computer.", 60),
            ("Account", 60), ("Username", 80)]
    if typed:
        body += [(USER, 220)]
    body += [("Full name", 80), ("Optional", 220), ("Password", 80), ("Password again", 80)]
    return page(6, "Account", body + buttons())


def confirm(encryption, user=USER, disk_path="/dev/vda", image="ghcr.io/tuna-os/marlin:niri  (this system, no download)"):
    body = [("Confirm installation", 60),
            (f"⚠ Everything on {disk_path} will be erased. This cannot be undone.", 60),
            ("Summary", 60)]
    rows = page(7, "Confirm", body + buttons("Install"), hint_action="Install")
    grid = [("Target disk", disk_path), ("Image", image), ("Filesystem", "btrfs"),
            ("Encryption", encryption), ("Username", user), ("Hostname", "marlin")]
    for label, value in grid:
        y = 20 + 18 * len(rows)
        rows.append((label, 80, y))
        rows.append((value, 300, y))
    return rows


PROGRESS = page(8, "Installing", [("Installing Marlin…", 60), ("Step 3 of 8 — Installing OS", 60),
                                  ("Do not power off the computer.", 60)], hint=False)
DONE = page(9, "Done", [("Marlin is installed", 520), ("Remove the installation media and restart the computer.", 480),
                        ("Restart now", 600)], hint=False)


class GridScreen(FakeScreen):
    """FakeScreen whose rows may carry an explicit y (summary grid)."""

    def __init__(self, rows, classify):
        laid = []
        for i, row in enumerate(rows):
            if isinstance(row, str):
                row = (row, 400)
            if len(row) == 3:
                text, x, y = row
            else:
                (text, x), y = row, 20 + 18 * i
            laid.append((text, (x, y, min(x + 6 * max(len(text), 2), self.width - 1), y + 14)))
        self.rows = laid
        self.lines = [text for text, _ in laid]
        self.state = classify(self.lines)


def frames_for(mode, confirm_page=None, product_frames=None):
    flow = (product_frames or [welcome()]) + [SESSION, SOURCE_PAGE, SOURCE_PAGE, disk(False), disk(True), enc(False)]
    flow += [enc(True), enc(True)] if mode == "luks" else [enc(False)]
    flow += [account(), account(True), account(True)]
    flow += [confirm_page or confirm("Passphrase" if mode == "luks" else "No encryption")]
    flow += [PROGRESS, PROGRESS, DONE]
    return flow


def run_install(mode, frames, tmp_path):
    frames = iter(frames)
    shown, typed, keys, clicks = {}, [], [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    def pointer(vnc, x, y, width, height, click=True):
        clicks.append((x, y))
        return True

    result = nd.drive(tmp_path, mode, "vnc", capture, keys.append, typed.append,
                      nd.BUNDLE_DIGEST, LUKS, USER, PASSWORD,
                      screen_factory=lambda path: GridScreen(shown[path], nd.classify),
                      pointer=pointer, sleep=lambda s: None, clock=lambda: 0.0)
    evidence = json.loads((tmp_path / "walkthrough-niri.json").read_text())
    return result, evidence, typed, clicks


def lines(rows):
    return [row[0] for row in rows]


@pytest.mark.parametrize("rows,state", [
    (welcome(), "welcome"), (SESSION, "session"), (SOURCE_PAGE, "source"), (disk(False), "disk"),
    (enc(False), "encryption"), (account(), "account"), (confirm("No encryption"), "confirm"),
    (PROGRESS, "progress"), (DONE, "done"), (["Installation failed"], "failed"),
    (["This computer does not meet the minimum requirements"], "requirements"),
    (["waybar", "12:00"], "unknown"),
])
def test_classify(rows, state):
    assert nd.classify(lines(rows) if rows and isinstance(rows[0], tuple) else rows) == state


def test_classify_without_the_top_bar_reads_headings():
    body = [r for r in lines(enc(False)) if not r.startswith("Step ")]
    assert nd.classify(body) == "encryption"
    assert nd.classify([r for r in lines(DONE) if not r.startswith("Step ")]) == "done"


@pytest.mark.parametrize("mode", ["plain", "luks"])
def test_install_creates_the_account_and_completes(tmp_path, mode):
    result, evidence, typed, clicks = run_install(mode, frames_for(mode), tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["completed"] and evidence["submitted"] and evidence["account_created"]
    assert evidence["transitions"] == [
        "welcome", "session", "source", "disk", "encryption", "account", "confirm", "progress", "done"]
    assert evidence["product"] == "Marlin"
    expected = ([LUKS, LUKS] if mode == "luks" else []) + [USER, PASSWORD, PASSWORD]
    assert typed == expected
    assert evidence["confirm"]["Username"] == USER
    # Secrets never reach the evidence transcript.
    assert PASSWORD not in json.dumps(evidence) and LUKS not in json.dumps(evidence)


def test_page_buttons_never_hit_the_hint_bar(tmp_path):
    _, evidence, _, _ = run_install("plain", frames_for("plain"), tmp_path)
    for click in evidence["clicks"]:
        if click["action"] in ("continue", "install"):
            assert click["point"][0] > 1000, click


def test_neutral_product_name_waits_for_branding(tmp_path):
    frames = frames_for("plain", product_frames=[welcome("Linux"), welcome("Linux"), welcome()])
    result, evidence, _, _ = run_install("plain", frames, tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["product"] == "Marlin"


@pytest.mark.parametrize("page_rows", [
    confirm("TPM + passphrase"), confirm("Passphrase", user="root"),
    confirm("Passphrase", disk_path="/dev/vdb"), confirm("Passphrase", image="ghcr.io/tuna-os/marlin:niri"),
])
def test_confirm_mismatch_is_never_submitted(tmp_path, page_rows):
    result, evidence, _, _ = run_install("luks", frames_for("luks", page_rows), tmp_path)
    assert result == 1 and evidence["submitted"] is False


def test_unpinned_installer_is_refused(tmp_path):
    result = nd.drive(tmp_path, "plain", "vnc", lambda *a, **k: None, print, print, "sha256:" + "0" * 64,
                      LUKS, USER, PASSWORD, sleep=lambda s: None, clock=lambda: 0.0)
    assert result == 1
    assert "digest" in json.loads((tmp_path / "walkthrough-niri.json").read_text())["error"]


def test_failure_page_fails_closed(tmp_path):
    frames = frames_for("plain")[:-1] + [["Installation failed"]]
    result, evidence, _, _ = run_install("plain", frames, tmp_path)
    assert result == 1 and evidence["completed"] is False


def test_requirements_gate_fails_closed(tmp_path):
    frames = [["This computer does not meet the minimum requirements", "Continue anyway"]]
    result, evidence, _, _ = run_install("plain", frames, tmp_path)
    assert result == 1 and "requirements" in evidence["error"]


GTK_USERNAME = ["12:00", "Username:", "Login"]
GTK_PASSWORD = ["12:00", "Password:", "Login"]
DMS_OFFERED = ["12:00", USER, "Password"]
HOTKEYS = ["Important Hotkeys", "Mod+T Spawn alacritty", "Mod+D Spawn fuzzel"]
LAUNCHER = ["Files", "Volume Control", "Nautilus"]


def run_login(phase, frames, tmp_path):
    frames = iter(frames)
    shown, typed, keys = {}, [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    result = fb.drive(tmp_path, phase, "vnc", capture, keys.append, typed.append, USER, PASSWORD,
                      screen_factory=lambda path: GridScreen([(t, 400) for t in shown[path]], fb.classify),
                      pointer=lambda *a, **k: True, sleep=lambda s: None, clock=lambda: 0.0)
    evidence = json.loads((tmp_path / f"first-boot-{phase}.json").read_text())
    return result, evidence, typed, keys


@pytest.mark.parametrize("phase", ["setup", "login"])
def test_gtkgreet_login_reaches_the_niri_session(tmp_path, phase):
    result, evidence, typed, keys = run_login(phase, [GTK_USERNAME, GTK_PASSWORD, HOTKEYS], tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["greeter_accepts_account"] == "typed"
    assert evidence["session_marker"] == "important hotkeys"
    assert typed == [USER, PASSWORD]
    assert PASSWORD not in json.dumps(evidence)


def test_offered_account_and_launcher_session(tmp_path):
    result, evidence, typed, keys = run_login("login", [DMS_OFFERED, ["waybar"], LAUNCHER], tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["greeter_accepts_account"] == "offered"
    assert evidence["session_marker"] == "launcher" and "meta_l-d" in keys
    assert typed == [PASSWORD]


def test_password_prompt_for_another_account_is_refused(tmp_path):
    result, evidence, typed, _ = run_login("login", [["12:00", "someone", "Password"]], tmp_path)
    assert result == 1 and typed == []


def test_rejected_password_fails_closed(tmp_path):
    result, evidence, _, _ = run_login("login", [GTK_USERNAME, GTK_PASSWORD, ["Login failed", "Username:"]], tmp_path)
    assert result == 1 and evidence["completed"] is False


def test_greeter_that_never_leaves_is_not_a_session(tmp_path):
    result, evidence, _, _ = run_login("login", [GTK_USERNAME, GTK_PASSWORD] + [GTK_PASSWORD] * 20, tmp_path)
    assert result == 1 and evidence["completed"] is False


def function(name):
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize("flavor,required", [("niri", True), ("gnome", True), ("lxqt", False)])
def test_first_boot_scope_covers_niri(flavor, required):
    result = subprocess.run(
        ["bash", "-c", function("strict_first_boot_required") + 'strict_first_boot_required plain'],
        env={"FLAVOR": flavor, "TUNAOS_XFCE_CANDIDATE": "0", "PATH": "/usr/bin:/bin"},
        capture_output=True, check=False, timeout=5)
    assert (result.returncode == 0) is required


def test_first_boot_gui_passes_the_flavor():
    body = function("strict_first_boot_gui")
    assert '0 "$flavor_name"' in body and "TUNAOS_E2E_INSTALL_USER" in body


def test_walkthrough_routes_niri_and_reset_clears_its_evidence():
    cli = (ROOT / "scripts/installer-walkthrough.py").read_text()
    assert 'mode_explicit and flavor == "niri"' in cli
    assert '"niri": "lib.niri_first_boot"' in cli
    assert 'walkthrough-${_reset_mode}/walkthrough-niri.json' in SOURCE
