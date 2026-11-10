"""KDE strict qualification: installer account step, greeter login, wiring.

scripts/lib/kde_installer_driver.py drives the bundled InstallerKde wizard,
whose account step creates the installed system's user;
scripts/lib/kde_first_boot.py proves the Plasma greeter offers that account
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
from lib import kde_first_boot as fb
from lib import kde_installer_driver as kd

SOURCE = (ROOT / "scripts/iso-e2e.sh").read_text()
USER, PASSWORD, LUKS = "tunaose2e", "harbor-sunset-4817", "tunaos-e2e-luks"


class FakeScreen:
    width, height = 1280, 800

    def __init__(self, lines, classify):
        self.lines = list(lines)
        self.rows = [(line, (400, 100 + 30 * i, 600, 120 + 30 * i)) for i, line in enumerate(lines)]
        self.state = classify(self.lines)

    boxes = kd.Screen.boxes
    box = kd.Screen.box
    has = kd.Screen.has
    value_below = kd.Screen.value_below
    near_box = kd.Screen.near_box

    def _strip_reads(self, top):
        return []


# Measured on grouper (run 42763004792): the welcome button is the product copy.
WELCOME = ["Welcome to Bonito", "This wizard will guide you through installing Bonito onto this computer.",
           "Get started >"]
DISK = ["Target Disk", "Choose the disk where Bonito will be installed.", "/dev/vda", "/dev/vda • 64G • VIRTIO",
        "Back", "Next >"]
ENC = ["Disk Encryption", "Encryption protects your files if the disk is lost or stolen.",
       "No encryption", "Passphrase", "TPM", "TPM + passphrase", "Back", "Next"]
ENC_PASS = ENC[:-2] + ["Passphrase", "Confirm passphrase", "Back", "Next"]
ACCOUNT = ["User Account", "Create the account you will sign in with. It can also administer this computer.",
           "Full name (optional)", "Username", "Password", "Confirm password", "Back", "Next"]
ACCOUNT_TYPED = ACCOUNT[:4] + [USER] + ACCOUNT[4:]


def confirm(encryption, user=USER, disk="/dev/vda"):
    return ["Confirm installation", "Everything on /dev/vda will be erased. This cannot be undone.",
            "Target disk", disk, "Filesystem", "xfs", "Encryption", encryption, "Hostname", "bonito",
            "Username", user, "Image", "the running live system", "Back", "Install"]


PROGRESS = ["Installing Bonito…", "Installing Bonito… /dev/vda. Do not power off the computer.", "Cancel"]
DONE = ["Bonito is installed", "Remove the installation media and restart the computer.", "Restart now"]


def frames_for(mode, confirm_page=None):
    enc = ["verify-disk"]
    flow = [WELCOME, DISK, DISK, ENC]
    if mode == "luks":
        flow += [ENC_PASS, ENC_PASS]
    else:
        flow += [ENC]
    flow += [ACCOUNT, ACCOUNT_TYPED, ACCOUNT_TYPED]
    page = confirm_page or confirm("Passphrase" if mode == "luks" else "No encryption")
    flow += [page, page]  # reached in private, then read again outside it
    flow += [PROGRESS, PROGRESS, DONE]
    return flow


def run_install(mode, frames, tmp_path, digest=None):
    frames = iter(frames)
    shown, typed, keys, clicks = {}, [], [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    def pointer(vnc, x, y, width, height, click=True):
        clicks.append((x, y))
        return True

    result = kd.drive(tmp_path, mode, "vnc", capture, keys.append, typed.append,
                      digest or kd.BUNDLE_DIGEST, LUKS, USER, PASSWORD,
                      screen_factory=lambda path: FakeScreen(shown[path], kd.classify),
                      pointer=pointer, sleep=lambda s: None, clock=lambda: 0.0)
    evidence = json.loads((tmp_path / "walkthrough-kde.json").read_text())
    return result, evidence, typed


@pytest.mark.parametrize("lines,state", [
    (WELCOME, "welcome"), (DISK, "disk"), (ENC, "encryption"), (ACCOUNT, "account"),
    (confirm("No encryption"), "confirm"), (PROGRESS, "progress"), (DONE, "done"),
    (["Installation failed"], "failed"), (["Plasma"], "unknown"),
])
def test_classify(lines, state):
    assert kd.classify(lines) == state


@pytest.mark.parametrize("mode", ["plain", "luks"])
def test_install_creates_the_account_and_completes(tmp_path, mode):
    result, evidence, typed = run_install(mode, frames_for(mode), tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["completed"] and evidence["submitted"] and evidence["account_created"]
    assert evidence["transitions"] == ["welcome", "disk", "encryption", "account", "confirm", "progress", "done"]
    expected = ([LUKS, LUKS] if mode == "luks" else []) + [USER, PASSWORD, PASSWORD]
    assert typed == expected
    assert evidence["confirm"]["Username"] == [USER]
    # Secrets never reach the evidence transcript.
    assert PASSWORD not in json.dumps(evidence) and LUKS not in json.dumps(evidence)


@pytest.mark.parametrize("page", [confirm("TPM + passphrase"), confirm("Passphrase", user="root"),
                                  confirm("Passphrase", disk="/dev/vdb")])
def test_confirm_mismatch_is_never_submitted(tmp_path, page):
    result, evidence, _ = run_install("luks", frames_for("luks", page), tmp_path)
    assert result == 1 and evidence["submitted"] is False


def test_unpinned_installer_is_refused(tmp_path):
    # An unmeasured bundle is driven for its frames but never passes.
    result, evidence, _ = run_install("plain", frames_for("plain", confirm("No encryption")), tmp_path,
                                      digest="sha256:" + "0" * 64)
    assert result == 1
    assert evidence["bundle_measured"] is False and "digest" in evidence["error"]


def test_failure_page_fails_closed(tmp_path):
    frames = frames_for("plain")[:-1] + [["Installation failed"]]
    result, evidence, _ = run_install("plain", frames, tmp_path)
    assert result == 1 and evidence["completed"] is False


GREETER = [USER, "Password", "Keyboard Layout: us", "Virtual Keyboard", "Switch User"]
LAUNCHER = [USER, "Search…", "Applications", "Places", "Favorites"]


def run_login(phase, frames, tmp_path):
    frames = iter(frames)
    shown, typed, keys = {}, [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    result = fb.drive(tmp_path, phase, "vnc", capture, keys.append, typed.append, USER, PASSWORD,
                      screen_factory=lambda path: FakeScreen(shown[path], fb.classify),
                      pointer=lambda *a, **k: True, sleep=lambda s: None, clock=lambda: 0.0)
    evidence = json.loads((tmp_path / f"first-boot-{phase}.json").read_text())
    return result, evidence, typed, keys


@pytest.mark.parametrize("phase", ["setup", "login"])
def test_greeter_login_opens_the_accounts_session(tmp_path, phase):
    result, evidence, typed, keys = run_login(phase, [GREETER, LAUNCHER], tmp_path)
    assert result == 0 and evidence["completed"] and evidence["session_user_observed"]
    assert typed == [PASSWORD] and "ret" in keys


def test_greeter_without_the_account_fails(tmp_path):
    result, evidence, typed, _ = run_login("setup", [["someone", "Password", "Switch User"]], tmp_path)
    assert result == 1 and typed == []


def test_launcher_of_another_user_fails(tmp_path):
    other = ["liveuser", "Search…", "Applications"]
    result, evidence, _, _ = run_login("login", [GREETER, other], tmp_path)
    assert result == 1 and not evidence["completed"]


def function(name):
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize("flavor,required", [("kde", True), ("gnome", True), ("kde-nvidia", True), ("niri", True), ("lxqt", False)])
def test_first_boot_scope_includes_kde(flavor, required):
    result = subprocess.run(
        ["bash", "-c", function("strict_first_boot_required") + 'strict_first_boot_required plain'],
        env={"FLAVOR": flavor, "TUNAOS_XFCE_CANDIDATE": "0", "PATH": "/usr/bin:/bin"},
        capture_output=True, check=False, timeout=5)
    assert (result.returncode == 0) is required


def test_first_boot_gui_passes_the_flavor(tmp_path):
    harness = function("strict_first_boot_gui") + """
e2e_phase() { :; }
python3() { echo "$*" >"$OUTPUT_DIR/argv"; return 0; }
strict_poweroff_installed() { :; }
strict_offline_evidence() { :; }
strict_first_boot_gui luks login
"""
    env = {"OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": "/s", "SERIAL_LOG": str(tmp_path / "serial"),
           "MONITOR_SOCK": "/m", "E2E_INSTALL_USER": USER, "FLAVOR": "kde", "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", "-c", harness], env=env, check=True, timeout=5)
    argv = (tmp_path / "argv").read_text().split()
    assert argv[4] == "kde" and "--first-boot=login" in argv


def test_disk_row_falls_back_to_the_subtitle():
    page = FakeScreen(["Choose the disk where Bonito will be installed.", "QEMU HARDDISK",
                       "/dev/vda • 64 GiB • VirtIO", "Next"], kd.classify)
    assert kd.disk_row(page) == page.rows[2][1]


def test_disk_row_reads_ocr_slash_confusions():
    # Measured: grouper run 42769339506 read the subtitle as below and the
    # title not at all.
    page = FakeScreen(["Choose the disk where Grouper will be installed.",
                       "idevivda + 64 GiB + virtlO", "< Back"], kd.classify)
    assert kd.disk_row(page) == page.rows[1][1]
    assert kd.device_text("Everything on idev/vda will be erased.") == "everything on /dev/vda will be erased."


def test_two_disks_are_refused():
    page = FakeScreen(["/dev/vda", "/dev/vda • 64 GiB", "x", "y", "/dev/vda • 32 GiB"], kd.classify)
    with pytest.raises(kd.Unverified):
        kd.disk_row(page)


def test_kde_label_match_survives_rn_read_as_m():
    # grouper run 42776467083: OCR read the account page's "Username" as "Usemame".
    from lib import kde_installer_driver as kd
    screen = kd.Screen.__new__(kd.Screen)
    screen.width, screen.height = 1280, 800
    screen.rows = [('Usemame', (384, 283, 448, 292)), ('Password', (384, 369, 442, 379))]
    screen.lines = [text for text, _ in screen.rows]
    assert screen.box('Username') == (384, 283, 448, 292)
    assert screen.has('Username')
    assert not screen.has('Confirm password')


def test_kde_confirm_row_label_is_found_within_two_edits():
    from lib import kde_installer_driver as kd
    screen = kd.Screen.__new__(kd.Screen)
    screen.width, screen.height = 1280, 800
    screen.rows = [('Hostname', (384, 405, 449, 414)), ('Userame', (384, 462, 448, 471)),
                   ('Uscrname', (384, 463, 448, 471)), ('tunaose2e', (384, 478, 451, 489))]
    screen.lines = [text for text, _ in screen.rows]
    screen._strip_reads = lambda top: []
    assert screen.value_below('Username') == ['tunaose2e']
    screen.rows.append(('Usernane', (384, 600, 448, 610)))
    with pytest.raises(kd.Unverified):
        screen.near_box('Username')
