"""COSMIC strict qualification: installer account page, greeter login, wiring.

scripts/lib/cosmic_installer_driver.py drives the bundled InstallerCosmic
wizard, whose account page creates the installed system's user;
scripts/lib/cosmic_first_boot.py proves cosmic-greeter offers that account
and its password opens a user session. These inert tests replay OCR frames
through both: no guest, no VNC, no OCR binaries. The frames are written from
the bootc-installer COSMIC copy (ui.rs, copy-defaults.json), not measured.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import cosmic_first_boot as fb
from lib import cosmic_installer_driver as cd

SOURCE = (ROOT / "scripts/iso-e2e.sh").read_text()
USER, PASSWORD, LUKS = "tunaose2e", "harbor-sunset-4817", "tunaos-e2e-luks"
MEASURED = "sha256:" + "1" * 64


class FakeScreen:
    """Each line is its own row unless given as (text, box)."""

    width, height = 1280, 800

    def __init__(self, lines, classify):
        self.rows = [line if isinstance(line, tuple) else (line, (400, 100 + 30 * i, 600, 120 + 30 * i))
                     for i, line in enumerate(lines)]
        self.lines = [text for text, _ in self.rows]
        self.state = classify(self.lines)

    boxes = cd.Screen.boxes
    box = cd.Screen.box
    has = cd.Screen.has
    matching = cd.Screen.matching
    value_beside = cd.Screen.value_beside

    def line_reads(self, box, right=None, left=20):
        return []


WELCOME = ["Welcome to Bonito",
           "Welcome. This assistant will guide you through installing Bonito onto this computer.",
           "You will choose a target disk and a few options, and create your account.", "Get started"]
LANGUAGE = ["Language", "The language of the installed system.", "en_US.UTF-8", "Back", "Continue"]
KEYBOARD = ["Keyboard", "The keyboard layout of the installed system.", "us", "Back", "Continue"]
TIMEZONE = ["Time zone", "Search, then pick where you are.", "Search time zones", "UTC", "Back", "Continue"]
DISK = ["Select a disk", "Everything on the disk you pick will be erased.", "/dev/vda",
        "/dev/vda · 64 GiB · VirtIO", "Back", "Continue"]
DISK_SCANNING = ["Select a disk", "Everything on the disk you pick will be erased.", "Scanning for disks…", "Back"]
OPTIONS_HEAD = ["Options", "Sensible defaults are already chosen. Change them only if you need to.", "System",
                "Computer name", "bonito", "Filesystem", "xfs", "Encryption", "Disk encryption"]
OPTIONS = OPTIONS_HEAD + ["No encryption", "Anyone with the disk can read your files.", "Back", "Continue"]
OPTIONS_MENU = OPTIONS_HEAD + ["No encryption", "Anyone with the disk can read your files.",
                               "No encryption", "Passphrase", "Back", "Continue"]
OPTIONS_PASS = OPTIONS_HEAD + ["Passphrase", "Enter a passphrase.", "Passphrase", "Required to unlock at boot",
                               "Confirm passphrase", "Type it again", "Back"]
# A private frame: even a revealed passphrase never reaches the evidence.
OPTIONS_TYPED = OPTIONS_HEAD + ["Passphrase", "You'll type it at every boot.", "Passphrase", LUKS,
                                "Confirm passphrase", "Back", "Continue"]
ACCOUNT_HEAD = ["Create your account", "You will sign in with this account. It can administer the computer.",
                "Account", "Username"]
ACCOUNT_TAIL = ["Full name", "Optional", "Password", "Required", "Confirm password", "Type it again", "Back"]
ACCOUNT = ACCOUNT_HEAD + ["Lowercase, for example alex"] + ACCOUNT_TAIL
ACCOUNT_USER = ACCOUNT_HEAD + [USER] + ACCOUNT_TAIL
ACCOUNT_DONE = ACCOUNT_HEAD + [USER, "Full name", "Optional", "Password", PASSWORD, "Confirm password",
                               "Back", "Continue"]
TOUR = ["Tour", "Your apps", "Everything you need, preinstalled.", "Back", "Continue"]
COMPANION = ["Use your phone",
             "Open the link on your phone to fill in your account. The code carries the session, so only it is shown here.",
             "On this computer", "10.0.2.15:8765", "Pairing code", "k3x9", "Waiting for your phone…",
             "Copy link", "Back", "Continue"]


def confirm(encryption, user=USER, disk="/dev/vda", image="this system (this system — no download)"):
    def row(i, label, value):
        y = 200 + 40 * i
        return [(label, (100, y, 260, y + 20)), (value, (700, y, 900, y + 20))]

    page = ["Confirm installation", "The last screen before anything is written.",
            f"Everything on {disk} will be erased. This cannot be undone.", "Summary"]
    page = [(text, (100, 40 + 30 * i, 900, 60 + 30 * i)) for i, text in enumerate(page)]
    for i, (label, value) in enumerate([("Target disk", disk), ("Filesystem", "xfs"), ("Encryption", encryption),
                                        ("Computer name", "bonito"), ("Username", user), ("Image", image)]):
        page += row(i, label, value)
    return page + [("Back", (100, 700, 160, 720)), ("Install", (1100, 700, 1180, 720))]


PROGRESS = ["Installing Bonito…", "fisherman is writing the image to disk.",
            "Step 3 of 10 — Setting up your drive…", "Do not power off the computer.", "Copy log"]
DONE = ["Bonito is installed", "Remove the installation media and restart the computer.",
        "Copy log", "Close", "Restart now"]
FAILED = ["Installation failed", "The install log above has the details.", "Copy log", "Close"]


def frames_for(mode, confirm_page=None, tour=False, companion=True):
    flow = [WELCOME, WELCOME, LANGUAGE, KEYBOARD, TIMEZONE, DISK, DISK]
    if mode == "luks":
        flow += [OPTIONS, OPTIONS, OPTIONS_MENU, OPTIONS_PASS, OPTIONS_PASS, OPTIONS_TYPED]
    else:
        flow += [OPTIONS, OPTIONS]
    flow += [ACCOUNT, ACCOUNT_USER, ACCOUNT_DONE]
    flow += ([TOUR, TOUR] if tour else []) + ([COMPANION] if companion else [])
    summary = confirm_page or confirm("Passphrase" if mode == "luks" else "No encryption")
    # Straight from the account the summary is captured privately, then
    # observed once more outside the private directory.
    flow += [summary] if (tour or companion) else [summary, summary]
    flow += [PROGRESS, PROGRESS, DONE]
    return flow


def run_install(mode, frames, tmp_path, digest=MEASURED):
    frames = iter(frames)
    shown, typed, keys, clicks, private = {}, [], [], [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        if directory:
            private.append(index)
        shown[path] = next(frames)
        return path

    def pointer(vnc, x, y, width, height, click=True, buttons=1):
        clicks.append((x, y))
        return True

    result = cd.drive(tmp_path, mode, "vnc", capture, keys.append, typed.append,
                      digest, LUKS, USER, PASSWORD,
                      screen_factory=lambda path: FakeScreen(shown[path], cd.classify),
                      pointer=pointer, sleep=lambda s: None, clock=lambda: 0.0)
    evidence = json.loads((tmp_path / "walkthrough-cosmic.json").read_text())
    return result, evidence, typed


@pytest.fixture
def measured(monkeypatch):
    # Replay frames carry a stand-in digest; pin it as the measured one.
    monkeypatch.setattr(cd, "BUNDLE_DIGEST", MEASURED)


@pytest.mark.parametrize("lines,state", [
    (WELCOME, "welcome"), (LANGUAGE, "language"), (KEYBOARD, "keyboard"), (TIMEZONE, "timezone"),
    (DISK, "disk"), (OPTIONS, "options"), (OPTIONS_PASS, "options"), (ACCOUNT, "account"),
    (TOUR, "tour"), (COMPANION, "companion"), ([t for t, _ in confirm("No encryption")], "confirm"),
    (PROGRESS, "progress"), (DONE, "done"), (FAILED, "failed"),
    (["Network", "The installer needs the network to fetch images.", "Recheck"], "network"),
    (["Exit Installer?", "Any progress will be lost.", "Cancel", "Exit"], "exit-dialog"),
    (["COSMIC"], "unknown"),
])
def test_classify(lines, state):
    assert cd.classify(lines) == state


# OCR rows of every kept frame of grouper run 42877983500 (harness 3e23b612),
# the run whose walk measured the pinned bundle.
RUN_42877983500 = json.loads((ROOT / "tests/fixtures/cosmic-installer/run42877983500.json").read_text())


@pytest.mark.parametrize("mode", ["plain", "luks"])
def test_measured_frames_replay_through_classify(mode):
    run = RUN_42877983500[mode]
    assert run["installer_digest"] == cd.BUNDLE_DIGEST
    states = [cd.classify(frame["text"]) for frame in run["frames"]]
    assert states == [frame["state"] for frame in run["frames"]]
    # Every page in order, once each, ending in the failure fisherman reported.
    walked = [s for i, s in enumerate(states) if s != "unknown" and (i == 0 or states[i - 1] != s)]
    assert walked == ["welcome", "disk", "options", "account", "confirm", "progress", "failed"]



@pytest.mark.parametrize("mode", ["plain", "luks"])
def test_install_creates_the_account_and_completes(tmp_path, measured, mode):
    result, evidence, typed = run_install(mode, frames_for(mode), tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["completed"] and evidence["submitted"] and evidence["account_created"]
    assert evidence["bundle_measured"] is True
    assert evidence["transitions"] == ["welcome", "language", "keyboard", "timezone", "disk", "options",
                                       "account", "companion", "confirm", "progress", "done"]
    expected = ([LUKS, LUKS] if mode == "luks" else []) + [USER, PASSWORD, PASSWORD]
    assert typed == expected
    assert evidence["confirm"]["Username"] == USER
    assert evidence["confirm"]["Encryption"] == ("Passphrase" if mode == "luks" else "No encryption")
    assert [c["action"] for c in evidence["clicks"]].count("install") == 1
    # Secrets never reach the evidence transcript.
    assert PASSWORD not in json.dumps(evidence) and LUKS not in json.dumps(evidence)


def test_a_bundle_without_preflight_pages_goes_straight_to_the_disk(tmp_path, measured):
    # grouper run 42779226693: "Step 2 of 7 - Select a disk" right after welcome.
    frames = [f for f in frames_for("plain") if f not in (LANGUAGE, KEYBOARD, TIMEZONE)]
    result, evidence, _ = run_install("plain", frames, tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["transitions"][:3] == ["welcome", "disk", "options"]


def test_preflight_pages_never_go_backwards(tmp_path, measured):
    frames = frames_for("plain")
    frames[2:5] = [TIMEZONE, LANGUAGE]
    result, evidence, _ = run_install("plain", frames, tmp_path)
    assert result == 1 and evidence["submitted"] is False


def test_pointer_is_parked_off_the_button_after_each_click(tmp_path, measured):
    moves = []

    def pointer(vnc, x, y, width, height, click=True, buttons=1):
        moves.append((x, y, click and buttons == 1, buttons))
        return True

    frames = iter(frames_for("plain"))
    shown = {}

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    result = cd.drive(tmp_path, "plain", "vnc", capture, lambda k: None, lambda t: None,
                      MEASURED, LUKS, USER, PASSWORD,
                      screen_factory=lambda path: FakeScreen(shown[path], cd.classify),
                      pointer=pointer, sleep=lambda s: None, clock=lambda: 0.0)
    assert result == 0
    # Every left click is followed straight away by a move to the left edge.
    clicks = [i for i, m in enumerate(moves) if m[2]]
    assert clicks
    assert all(moves[i + 1][:3] == (2, 400, False) for i in clicks)


def test_the_install_log_is_wheeled_to_its_end_while_installing(tmp_path, measured):
    # grouper run 42877983500 failed with only the log's head ever shown.
    wheels = []

    def pointer(vnc, x, y, width, height, click=True, buttons=1):
        if buttons == 16:
            wheels.append((x, y))
        return True

    frames = iter(frames_for("plain")[:-1] + [FAILED])
    shown = {}

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    result = cd.drive(tmp_path, "plain", "vnc", capture, lambda k: None, lambda t: None,
                      MEASURED, LUKS, USER, PASSWORD,
                      screen_factory=lambda path: FakeScreen(shown[path], cd.classify),
                      pointer=pointer, sleep=lambda s: None, clock=lambda: 0.0)
    evidence = json.loads((tmp_path / "walkthrough-cosmic.json").read_text())
    assert result == 1 and evidence["error"] == "installer reported failure"
    follows = [c for c in evidence["clicks"] if c["action"] == "follow log"]
    # Both progress frames (submission's and the first poll's), at the
    # centre of the screen, inside the log card.
    assert [c["state"] for c in follows] == ["progress", "progress"]
    assert wheels.count((640, 400)) == 60


def test_companion_page_with_its_subtitle_wrapped_is_still_the_companion():
    # A narrow window wraps the subtitle; OCR passes interleave its halves.
    lines = ["Use your phone", "Open the link on your phone to fill in", "On this computer",
             "your account. The code carries the session,", "Pairing code", "Back", "Continue"]
    assert cd.classify(lines) == "companion"


def test_confirm_rows_below_the_fold_are_read_after_a_scroll(tmp_path, measured):
    full = confirm("No encryption")
    top = [r for r in full if r[0] not in ("Username", USER, "Image", "this system (this system — no download)")]
    bottom = [r for r in full if r[0] not in ("Target disk", "/dev/vda")]
    frames = frames_for("plain", top)
    at = frames.index(top)
    frames[at + 1:at + 1] = [bottom]
    result, evidence, _ = run_install("plain", frames, tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["confirm"]["Username"] == USER


def test_tour_slides_are_walked_to_the_companion(tmp_path, measured):
    result, evidence, _ = run_install("plain", frames_for("plain", tour=True), tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["transitions"][6:9] == ["account", "tour", "tour"]


def test_disk_rows_are_awaited_while_scanning(tmp_path, measured):
    frames = frames_for("plain")
    frames[5:5] = [DISK_SCANNING]
    result, evidence, _ = run_install("plain", frames, tmp_path)
    assert result == 0, evidence.get("error")


def test_a_skipped_account_page_fails_closed(tmp_path, measured):
    frames = frames_for("plain")
    frames = frames[:8] + [COMPANION]
    result, evidence, typed = run_install("plain", frames, tmp_path)
    assert result == 1 and evidence["submitted"] is False and typed == []


@pytest.mark.parametrize("page", [confirm("TPM + passphrase"), confirm("Passphrase", user="root"),
                                  confirm("Passphrase", disk="/dev/vdb"),
                                  confirm("Passphrase", image="ghcr.io/example/system:latest")])
def test_confirm_mismatch_is_never_submitted(tmp_path, measured, page):
    result, evidence, _ = run_install("luks", frames_for("luks", page), tmp_path)
    assert result == 1 and evidence["submitted"] is False
    assert "install" not in [c["action"] for c in evidence["clicks"]]


@pytest.mark.parametrize("digest", [None, "", MEASURED])
def test_unmeasured_installer_never_passes(tmp_path, monkeypatch, digest):
    # With no digest pinned, even a clean walk fails closed.
    monkeypatch.setattr(cd, "BUNDLE_DIGEST", None)
    result, evidence, _ = run_install("plain", frames_for("plain"), tmp_path, digest=digest)
    assert result == 1 and evidence["completed"] is True
    assert evidence["bundle_measured"] is False and "digest" in evidence["error"]


def test_unpinned_installer_is_refused(tmp_path, measured):
    result, evidence, _ = run_install("plain", frames_for("plain"), tmp_path, digest="sha256:" + "0" * 64)
    assert result == 1
    assert evidence["bundle_measured"] is False and "digest" in evidence["error"]


def test_failure_page_fails_closed(tmp_path, measured):
    frames = frames_for("plain")[:-1] + [FAILED]
    result, evidence, _ = run_install("plain", frames, tmp_path)
    assert result == 1 and evidence["completed"] is False


GREETER = ["10:42", "Tuesday, November 10", USER, "Password:"]
LAUNCHER = ["Type to search apps or type “?” for more options..."]
LIBRARY = ["Type to search apps…", "Library Home", "Office", "System", "Utilities"]


SETUP_PAGE = ["Accessibility setup", "Screen reader", "Magnifier", "Display scaling", ("Next", (894, 515, 957, 545))]


def run_login(phase, frames, tmp_path, clicks=None):
    frames = iter(frames)
    shown, typed, keys = {}, [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    result = fb.drive(tmp_path, phase, "vnc", capture, keys.append, typed.append, USER, PASSWORD,
                      screen_factory=lambda path: FakeScreen(shown[path], fb.classify),
                      pointer=lambda *a, **k: (clicks.append(a) if clicks is not None else None) or True,
                      sleep=lambda s: None, clock=lambda: 0.0)
    evidence = json.loads((tmp_path / f"first-boot-{phase}.json").read_text())
    return result, evidence, typed, keys


@pytest.mark.parametrize("phase", ["setup", "login"])
@pytest.mark.parametrize("session", [LAUNCHER, LIBRARY])
def test_greeter_login_opens_a_user_session(tmp_path, phase, session):
    result, evidence, typed, keys = run_login(phase, [GREETER, session], tmp_path)
    assert result == 0 and evidence["completed"] and evidence["session_observed"]
    assert evidence["greeter_offers_account"]
    assert typed == [PASSWORD] and "ret" in keys and "meta_l" in keys
    assert PASSWORD not in json.dumps(evidence)


@pytest.mark.parametrize("phase", ["setup", "login"])
@pytest.mark.parametrize("failure", [
    "Incorrect password. Please check your keyboard layout and try again.",
    "Authentication failed. Please try again.", "Login failed"])
def test_a_rejected_password_fails_closed(tmp_path, phase, failure):
    result, evidence, typed, _ = run_login(phase, [GREETER, [USER, "Password:", failure]], tmp_path)
    assert result == 1 and not evidence["completed"]
    assert "rejected" in evidence["error"]


def test_greeter_without_the_account_fails(tmp_path):
    result, evidence, typed, _ = run_login("setup", [["10:42", "someone", "Password:"]], tmp_path)
    assert result == 1 and typed == []


def test_a_greeter_that_never_reaches_a_session_fails(tmp_path):
    result, evidence, _, _ = run_login("login", [GREETER] + [GREETER] * 12, tmp_path)
    assert result == 1 and not evidence["completed"]


def function(name):
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize("mode,required", [("plain", True), ("luks", True)])
def test_first_boot_scope_includes_cosmic(mode, required):
    result = subprocess.run(
        ["bash", "-c", function("strict_first_boot_required") + f"strict_first_boot_required {mode}"],
        env={"FLAVOR": "cosmic", "TUNAOS_XFCE_CANDIDATE": "0", "PATH": "/usr/bin:/bin"},
        capture_output=True, check=False, timeout=5)
    assert (result.returncode == 0) is required


class _SizeOnlyScreen(FakeScreen):
    """A maximized disk page: whole-frame OCR keeps only the size cell."""

    def __init__(self, reads):
        super().__init__(["Select a disk", ("64 GiB", (116, 258, 151, 267)), "Back", "Continue"], cd.classify)
        self.reads = reads

    def line_reads(self, box, right=None):
        return self.reads


def test_disk_row_falls_back_to_the_enlarged_subtitle_line():
    row = cd.target_row(_SizeOnlyScreen(["/devivda - 64 GiB - VirtiO"]))
    assert row == (20, 258, 151, 267)


def test_disk_row_fallback_refuses_another_disk():
    with pytest.raises(cd.Unverified):
        cd.target_row(_SizeOnlyScreen(["/dev/vdb - 64 GiB - VirtIO"]))


class _BlankListScreen(FakeScreen):
    """A maximized disk page where whole-frame OCR saw no disk text at all."""

    def __init__(self, target_y):
        super().__init__([("Select a disk", (34, 123, 204, 145)), ("Back", (50, 673, 79, 684)),
                          ("Continue", (1164, 673, 1224, 684))], cd.classify)
        self.target_y = target_y

    def line_reads(self, box, right=None):
        return ["/dev/vda - 64 GiB - VirtIO"] if abs(box[1] - self.target_y) <= 6 else ["~"]


def test_disk_row_scans_the_list_when_no_size_cell_was_read():
    screen = _BlankListScreen(target_y=0)
    heading = screen.box("Select a disk")
    screen.target_y = heading[3] + 20 + 24
    row = cd.target_row(screen)
    assert row[0] == 20 and abs(row[1] - screen.target_y) <= 6


def test_disk_row_scan_fails_closed_with_what_it_saw():
    with pytest.raises(cd.Unverified, match="rows"):
        cd.target_row(_BlankListScreen(target_y=-1000))


def test_a_cut_short_placeholder_is_found_by_its_prefix():
    screen = FakeScreen(["Options", ("Required to unlock at", (1005, 479, 1142, 492)),
                         ("Type it again", (1004, 529, 1085, 542))], cd.classify)
    assert cd.hint_box(screen, cd.PASSPHRASE_HINT) == (1005, 479, 1142, 492)


def test_a_short_fragment_is_not_taken_for_a_placeholder():
    screen = FakeScreen(["Options", ("Required", (1005, 479, 1062, 492))], cd.classify)
    with pytest.raises(cd.Unverified):
        cd.hint_box(screen, cd.PASSPHRASE_HINT)


def test_an_image_without_tour_or_companion_goes_from_account_to_confirm(tmp_path, measured):
    result, evidence, _ = run_install("plain", frames_for("plain", companion=False), tmp_path)
    assert result == 0, evidence.get("error")
    assert evidence["transitions"][6:8] == ["account", "confirm"]


class _FragmentScreen(FakeScreen):
    """The confirm summary with the target disk value read only as fragments
    by whole-frame OCR (grouper run 42841652621) and whole by a line read."""

    def __init__(self, reads):
        lines = [("Target disk", (57, 300, 140, 316)), ("id", (1150, 300, 1160, 316)),
                 ("la", (1170, 300, 1180, 316))]
        super().__init__(lines, cd.classify)
        self._reads = reads

    def line_reads(self, box, right=None, left=20):
        assert left > box[2] and right == self.width - 40
        return list(self._reads)


def test_confirm_value_falls_back_to_a_line_read():
    screen = _FragmentScreen(["/dev/vda", "/devivda"])
    accept = lambda value: cd.device_text(value) == cd.TARGET_DISK
    assert screen.value_beside("Target disk", accept=accept) == "/dev/vda"


def test_confirm_value_refuses_another_disk_on_the_line_read():
    screen = _FragmentScreen(["/dev/vdb"])
    accept = lambda value: cd.device_text(value) == cd.TARGET_DISK
    with pytest.raises(cd.Unverified, match="reads"):
        screen.value_beside("Target disk", accept=accept)


def test_confirm_frame_is_kept_outside_the_private_directory(tmp_path, measured):
    result, evidence, _ = run_install("plain", frames_for("plain", companion=False), tmp_path)
    assert result == 0, evidence.get("error")
    confirms = [frame for frame in evidence["frames"] if frame["state"] == "confirm"]
    assert confirms[0].get("private") and not confirms[-1].get("private")


@pytest.mark.parametrize("line,named", [
    ("A Everything on /dev/vda will be erased. This cannot be undone.", True),
    ("Everything on /devivda will be erased. This cannot be undone.", True),
    ("Everything on /dev/vdb will be erased. This cannot be undone.", False),
    ("Not everything on /dev/vda will be erased. This cannot be undone.", False),
])
def test_erase_warning_read_behind_its_icon(line, named):
    warning = f"Everything on {cd.TARGET_DISK} will be erased. This cannot be undone."
    assert cd.names_warning(line, warning) is named


def test_progress_without_its_note():
    # run 42865163583: the orange "Do not power off" note went unread.
    lines = ["Installing Grouper...", "fisherman is wrie ag she image co dis", "[fisherman] version", "dev",
             "[1/9] Partitionirg disk"]
    assert cd.classify(lines) == "progress"
    assert cd.classify(["Installing Grouper..."]) == "unknown"


def test_greeter_prompt_is_read_under_the_account_name():
    # skipjack run 42911846504, strict-plain-installed: whole-frame OCR read
    # the account but dropped the dim "Password:" placeholder (confidence
    # 25), so 60 frames of a ready greeter classified as unknown.
    import shutil
    if not (shutil.which("convert") and shutil.which("tesseract")):
        pytest.skip("ImageMagick convert and tesseract are required")
    frame = ROOT / "tests/fixtures/cosmic-first-boot/greeter42911846504-plain.png"
    assert fb.Screen(frame).state == "unknown"
    screen = fb.Screen(frame, USER)
    assert screen.state == "greeter" and screen.has(USER)
    # Another account's name gives no strip to read the prompt from.
    assert fb.Screen(frame, "someoneelse").state == "unknown"


def test_cosmic_initial_setup_is_stepped_through_before_the_session_is_proven(tmp_path):
    """skipjack run 42931450791: login worked, then "Accessibility setup" sat over
    the desktop on both legs and Super never opened the launcher.
    Falsification: behavioural. Without the initial-setup state the driver sends
    Super at the dialog for its whole bound and fails 'no user session launcher'."""
    clicks = []
    result, evidence, _, keys = run_login("setup", [GREETER, SETUP_PAGE, SETUP_PAGE, SETUP_PAGE[:0] + ["desktop"], LAUNCHER], tmp_path, clicks)
    assert result == 0 and evidence["session_observed"]
    assert evidence["initial_setup_pages"] == ["Accessibility setup"] * 2
    assert len(clicks) == 2 and clicks[0][1:3] == (925, 530)
    assert keys.count("meta_l") == 2


def test_an_initial_setup_that_never_ends_fails_closed(tmp_path):
    result, evidence, _, _ = run_login("setup", [GREETER] + [SETUP_PAGE] * 20, tmp_path, [])
    assert result == 1 and not evidence["completed"]
    assert "initial setup" in evidence["error"]
