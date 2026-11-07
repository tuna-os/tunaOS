"""GNOME Initial Setup account creation and GDM login are proven, never assumed.

The driver in scripts/lib/gnome_first_boot.py runs on the installed system's
first and second boots. These inert tests replay OCR frames through it: no
guest, no VNC, no OCR binaries.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import gnome_first_boot as fb

SOURCE = (ROOT / "scripts/iso-e2e.sh").read_text()
USER, PASSWORD = "tunaose2e", "tunaose2e"


class FakeScreen:
    width, height = 1280, 800

    def __init__(self, lines):
        self.lines = list(lines)
        self.rows = [(line, (543, 550, 737, 594) if line == PILL else (10 + i, 110 + 20 * i, 200 + i, 125 + 20 * i))
                     for i, line in enumerate(lines)]
        self.state = fb.classify(self.lines)

    box = fb.Screen.box
    has = fb.Screen.has
    start_action = fb.Screen.start_action


WELCOME = ["Welcome", "Deutsch", "English", "Unspecified", "Next"]
TYPING = ["Typing", "English (US)", "Next"]
PRIVACY = ["Privacy", "Location Services", "Next"]
ABOUT = ["About You", "Full Name", "Username", "Next"]
ABOUT_TYPED = ABOUT + [USER]
PASSWORD_PAGE = ["Set a Password for tunaose2e", "Password", "Confirm Password", "Next"]
COMPLETE = ["Setup Complete", "Start Using Skipjack"]
PILL = "» Soe"  # a garbled read of the slate pill's label
COMPLETE_UNREAD = ["Setup Complete", "All done!", "Bonito is ready to be used.", PILL]
SESSION = ["Q Type to search"]
TOUR = ["Welcome to Bonito", "If you want t", "Skip"]
UBUNTU_PRO = ["Previous", "Ubuntu Pro", "Skip", "Enable Ubuntu Pro", "Skip for now"]
GREETER = [USER, "Not listed?"]
GREETER_PASSWORD = [USER, "Password"]


def run(phase, frames, tmp_path, user=USER):
    frames = iter(frames)
    shown, typed, keys = {}, [], []

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = next(frames)
        return path

    result = fb.drive(
        tmp_path, phase, "vnc", capture, keys.append, typed.append, user, PASSWORD,
        screen_factory=lambda path: FakeScreen(shown[path]), pointer=lambda *a, **k: True,
        sleep=lambda s: None, clock=lambda: 0.0,
    )
    evidence = json.loads((tmp_path / f"first-boot-{phase}.json").read_text())
    return result, evidence, typed, keys


@pytest.mark.parametrize(
    "lines,state",
    [
        (WELCOME, "language"), (["Welcome!", "English", "Unspecified v", "Next"], "language"),
        (["Welcome!", "English", "Unspecified", "Next"], "language"), (TYPING, "setup-page"), (ABOUT, "account"), (PASSWORD_PAGE, "password"),
        (COMPLETE, "setup-complete"), (TOUR, "tour"), (UBUNTU_PRO, "skip-page"), (SESSION, "session"), (GREETER_PASSWORD, "greeter-password"),
        (GREETER, "unknown"),
    ],
)
def test_classify(lines, state):
    assert fb.classify(lines) == state


def test_setup_creates_account_and_reaches_session(tmp_path):
    frames = [WELCOME, WELCOME, TYPING, PRIVACY, ABOUT, ABOUT_TYPED, PASSWORD_PAGE, PASSWORD_PAGE,
              COMPLETE, SESSION]
    result, evidence, typed, keys = run("setup", frames, tmp_path)
    assert result == 0
    assert evidence["completed"] is True
    assert evidence["account_name_observed"] is True
    assert typed == [USER, PASSWORD, PASSWORD]
    assert keys == ["ctrl-a", "ctrl-a", "ctrl-a"]
    # The frame taken after the password is typed is private: no file name
    # or OCR transcript of it leaves the run.
    assert [f for f in evidence["frames"] if f.get("private")] == [{"state": "password", "private": True}]
    assert [c["label"] for c in evidence["clicks"]] == [
        "English", "Next", "Next", "Next", "Next", "Password", "Confirm Password", "Next", "Start Using Skipjack"]


def test_setup_skips_the_first_login_tour(tmp_path):
    frames = [WELCOME, WELCOME, TYPING, PRIVACY, ABOUT, ABOUT_TYPED, PASSWORD_PAGE, PASSWORD_PAGE,
              COMPLETE, TOUR, TOUR, SESSION]
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert evidence["tour_skipped"] is True
    assert evidence["clicks"][-1]["label"] == "Skip"


def test_a_tour_that_never_goes_away_is_not_a_session(tmp_path):
    frames = [WELCOME, WELCOME, TYPING, PRIVACY, ABOUT, ABOUT_TYPED, PASSWORD_PAGE, PASSWORD_PAGE,
              COMPLETE] + [TOUR] * 60
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 1 and evidence["completed"] is False


def test_setup_clicks_the_start_pill_when_its_label_is_not_read(tmp_path):
    frames = [WELCOME, WELCOME, TYPING, PRIVACY, ABOUT, ABOUT_TYPED, PASSWORD_PAGE, PASSWORD_PAGE,
              COMPLETE_UNREAD, SESSION]
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 0
    last = evidence["clicks"][-1]
    assert last["label"] == "Start Using Bonito" and last["point"] == [640, 572]


def test_setup_complete_needs_exactly_one_action_pill(tmp_path):
    for frame in (COMPLETE_UNREAD[:-1], COMPLETE_UNREAD + [PILL]):
        result, evidence, _, _ = run("setup", [WELCOME, WELCOME, TYPING, ABOUT_TYPED, frame], tmp_path)
        assert result == 1 and evidence["completed"] is False


@pytest.mark.parametrize(
    "frames,why",
    [
        ([WELCOME, WELCOME, TYPING, PRIVACY, ABOUT, ABOUT], "typed account name not shown"),
        ([WELCOME, WELCOME, ["Typing", "Next"]], "does not offer English (US)"),
        ([COMPLETE] + [COMPLETE] * 60, "no session/tour frame"),
        ([GREETER_PASSWORD] * 60, "no language/timezone/setup-page"),
    ],
)
def test_setup_fails_closed(tmp_path, frames, why):
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 1
    assert evidence["completed"] is False
    assert why in evidence["error"]


def test_login_requires_the_created_account_and_a_session(tmp_path):
    result, evidence, typed, keys = run("login", [GREETER, SESSION], tmp_path)
    assert result == 0
    assert evidence["greeter_offers_account"] is True
    assert typed == [PASSWORD] and keys == ["ret"]
    assert evidence["clicks"][0]["label"] == USER


def test_login_rejects_a_greeter_without_the_account(tmp_path):
    other = ["someoneelse", "Not listed?"]
    result, evidence, typed, _ = run("login", [other, other], tmp_path)
    assert result == 1
    assert "does not offer the GUI-created account" in evidence["error"]
    assert typed == []


def test_login_without_session_is_not_proven(tmp_path):
    result, evidence, _, _ = run("login", [GREETER_PASSWORD] + [GREETER_PASSWORD] * 40, tmp_path)
    assert result == 1
    assert evidence["completed"] is False


@pytest.mark.parametrize("user", ["Root", "a", "has space"])
def test_rejects_untypeable_accounts(tmp_path, user):
    result, _, typed, _ = run("setup", [], tmp_path, user=user)
    assert result == 1 and typed == []


def function(name):
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize(
    "mode,flavor,candidate,required",
    [("plain", "gnome", "0", True), ("luks", "gnome", "0", True),
     ("plain", "niri", "0", True), ("plain", "xfce", "0", False),
     ("plain", "gnome", "1", False)],
)
def test_first_boot_scope(mode, flavor, candidate, required):
    result = subprocess.run(
        ["bash", "-c", function("strict_first_boot_required") + 'strict_first_boot_required "$1"', "t", mode],
        env={"FLAVOR": flavor, "TUNAOS_XFCE_CANDIDATE": candidate, "PATH": "/usr/bin:/bin"},
        capture_output=True, check=False, timeout=5,
    )
    assert (result.returncode == 0) is required


@pytest.mark.parametrize("rc,expected", [(0, 0), (1, 8)])
def test_first_boot_gui_fails_closed(tmp_path, rc, expected):
    harness = function("strict_first_boot_gui") + f"""
e2e_phase() {{ :; }}
python3() {{ echo "$*" >"$OUTPUT_DIR/argv"; return {rc}; }}
strict_poweroff_installed() {{ touch "$OUTPUT_DIR/poweroff"; }}
strict_offline_evidence() {{ echo "$1" >>"$OUTPUT_DIR/evidence"; }}
strict_first_boot_gui plain setup
"""
    env = {"OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": "/s", "SERIAL_LOG": str(tmp_path / "serial"),
           "MONITOR_SOCK": "/m", "E2E_INSTALL_USER": USER, "E2E_INSTALL_PASSWORD": PASSWORD,
           "PATH": "/usr/bin:/bin"}
    result = subprocess.run(["bash", "-c", harness], env=env, capture_output=True, check=False, timeout=5)
    assert result.returncode == expected
    assert "--first-boot=setup" in (tmp_path / "argv").read_text()
    assert (tmp_path / "poweroff").exists() == (expected != 0)
    assert ((tmp_path / "evidence").exists()) == (expected == 0)


def test_fresh_password_page_relies_on_initial_focus(tmp_path):
    # Run 41976637118: the focused field's small label is not OCR-readable.
    fresh = ["Set a Password for tunaose2e", "Confirm Password", "Next"]
    frames = [WELCOME, WELCOME, TYPING, PRIVACY, ABOUT, ABOUT_TYPED, fresh, fresh, COMPLETE, SESSION]
    result, evidence, typed, _ = run("setup", frames, tmp_path)
    assert result == 0
    assert typed == [USER, PASSWORD, PASSWORD]
    assert "Password" not in [c["label"] for c in evidence["clicks"]]


def _header_screen(monkeypatch, fill):
    """A 1280x800 capture whose 120px header band holds one action pill at
    (1078,38)-(1146,72) in `fill`, GIS's window edge at x=1152 and maroon
    wallpaper beyond it; OCR of the pill's inside reads 'Next'."""
    from types import SimpleNamespace
    width, band = 1280, 120
    pixels = bytearray(b"\xfa\xfa\xfa" * width * band)
    for y in range(band):
        for x in range(1153, width):
            pixels[(y * width + x) * 3:(y * width + x) * 3 + 3] = bytes((120, 40, 80))
    for y in range(38, 72):
        for x in range(1078, 1146):
            if not 1100 <= x < 1118 or not 50 <= y < 60:          # label strokes
                pixels[(y * width + x) * 3:(y * width + x) * 3 + 3] = bytes(fill)
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t10\t10\t60\t30\t95\tNext\n")

    def run(command, **options):
        return SimpleNamespace(stdout=bytes(pixels) if command[-1] == "rgb:-" else tsv)
    monkeypatch.setattr(fb.subprocess, "run", run)
    screen = object.__new__(fb.Screen)
    screen.path, screen.width, screen.height = Path("header.png"), width, 800
    return screen


@pytest.mark.parametrize("fill", [(111, 131, 150), (101, 123, 105), (233, 84, 32), (53, 132, 228)])
def test_the_action_pill_is_found_whatever_the_products_fill(monkeypatch, fill):
    # Skipjack/Bonito slate, Grouper's muted olive (run 42318386139), orange, blue.
    screen = _header_screen(monkeypatch, fill)
    found = screen._slate_action(0, 120, x_span=(128, 1152))
    assert [text for text, _ in found] == ["Next"]
    assert found[0][1] == (1078, 38, 1146, 72)


@pytest.mark.parametrize("fill", [(250, 250, 250), (0, 0, 0), (220, 220, 221)])
def test_plain_grey_ui_is_never_an_action_pill(monkeypatch, fill):
    assert _header_screen(monkeypatch, fill)._slate_action(0, 120, x_span=(128, 1152)) == []


def test_setup_skips_an_optional_page_that_offers_only_skip(tmp_path):
    # Run 42374980522 (grouper:gnome): Ubuntu Pro sits between password and the end.
    frames = [WELCOME, WELCOME, TYPING, PRIVACY, ABOUT, ABOUT_TYPED, PASSWORD_PAGE, PASSWORD_PAGE,
              UBUNTU_PRO, COMPLETE, SESSION]
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert "skip-page" in evidence["pages"]
    assert [c["label"] for c in evidence["clicks"]][-2:] == ["Skip", "Start Using Skipjack"]
