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
    assert evidence["tour_skips"] == 3
    assert "tour did not close after Skip" in evidence["error"]


def test_a_tour_that_ignores_the_first_skip_is_clicked_again(tmp_path):
    # bonito:gnome-nvidia run 42828790225, LUKS leg: the first Skip click
    # left the tour up (frames 14-36) while the plain leg's closed it.
    frames = [WELCOME, WELCOME, TYPING, PRIVACY, ABOUT, ABOUT_TYPED, PASSWORD_PAGE, PASSWORD_PAGE,
              COMPLETE, TOUR] + [TOUR] * 6 + [TOUR, SESSION]
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert evidence["tour_skips"] == 2
    assert [c["label"] for c in evidence["clicks"]][-2:] == ["Skip", "Skip"]


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
     ("plain", "kde", "0", True), ("luks", "kde-nvidia", "0", True), ("plain", "gnome", "1", False),
     # Overlay flavors keep their desktop's first-boot contract.
     ("plain", "gnome-hwe", "0", True), ("luks", "gnome-nvidia", "0", True),
     ("plain", "gnome-nvidia-hwe", "0", True), ("plain", "", "0", False),
     ("plain", "niri", "0", True), ("plain", "xfce", "0", True), ("plain", "lxqt", "0", False)],
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


CITY = fb.TIMEZONE_CITY
TZ_BLURB = ("The time zone will be set automatically if your location can be found. "
            "You can also search for a city to set it yourself.")
# Trimmed but classification-faithful frames from iso-builder runs 42488951825,
# 42518150255 and 42530591039 (grouper:gnome plain and LUKS legs): typed
# 'london', dropdown lists four Londons, the UK row is clicked, Next enables
# (setup-page). The commit can be slow offline, so the first re-observe still
# shows the time zone page; the Next click can also be truly lost, returning
# the page with the city still displayed and Next unread. The other Londons
# (Kiribati here) distinguish open result rows from a displayed-but-lost
# selection: the lost page shows only the chosen city plus its map tooltip.
# The ANR frame is the shell's "is not responding" dialog over that page.
TZ_FRESH = ["Previous", "Time Zone", TZ_BLURB]
TZ_RESULTS = TZ_FRESH + ["london", "London, Kiribati", CITY,
                         "London, Ontario, Canada", "London, Kentucky, United States"]
TZ_SELECTED = ["Previous", "Time Zone", TZ_BLURB, CITY, "GMT (UTC+00)",
               "London, United Kingdom", "15:31", "Next"]
TZ_LOST = ["Previous", "Time Zone", TZ_BLURB, CITY, "GMT (UTC+00)",
           "London, United Kingdom", "15:31"]


TZ_HELP = ["Previous", "Help Improve Ubuntu", "Share system data", "Next"]
# Pixel-faithful Location Services frame from iso-builder run 42582907974
# (grouper:gnome first boot): the OCR reads "on" from the page prose
# ("Turn on location services...") while the switch pill is pixel-off.
LOC_ON = ["Previous", "Location Services", "on",
          "Turn on location services to let applications know your geographical location.",
          "Next"]


def test_location_prose_never_counts_as_a_switch(tmp_path):
    # Run 42582907974: the driver clicked the OCR word "on" in the prose,
    # missed the pixel-off switch, recorded "on", and both legs wedged
    # anyway. Without pixel verification there is no blind click and the
    # state is recorded honestly; the flow continues to Setup Complete.
    frames = [LOC_ON, COMPLETE, SESSION]
    result, evidence, typed, _ = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert evidence.get("location_services") == "unknown"
    assert typed == []
    assert [c["label"] for c in evidence["clicks"]] == ["Next", "Start Using Skipjack"]


def _band_pixels(monkeypatch, width, height, paint):
    """A capture whose switch band holds `paint(x, y)` RGB triples."""
    from types import SimpleNamespace
    left, top = int(width * 0.55), int(height * 0.60)
    band_width, band_height = int(width * 0.35), int(height * 0.18)
    pixels = bytearray(b"\xfa\xfa\xfa" * band_width * band_height)
    for y in range(band_height):
        for x in range(band_width):
            triple = paint(x, y)
            if triple is not None:
                pixels[(y * band_width + x) * 3:(y * band_width + x) * 3 + 3] = bytes(triple)

    def run(command, **options):
        assert command[-1] == "rgb:-"
        return SimpleNamespace(stdout=bytes(pixels))
    monkeypatch.setattr(fb.subprocess, "run", run)
    return left, top


def test_location_probe_clicks_only_a_verified_on_pill(monkeypatch, tmp_path):
    # An Ubuntu-orange pill in the switch band reports on with its
    # centroid; a grey switch, prose, and wallpaper report unknown.
    left, top = _band_pixels(monkeypatch, 1280, 800,
                             lambda x, y: (233, 84, 32) if 136 <= x < 186 and 50 <= y < 78 else None)
    state, center = fb.probe_location_switch("frame.png", 1280, 800)
    assert state == "on"
    assert center == (left + 160, top + 63)


def test_location_probe_ignores_a_grey_switch(monkeypatch):
    _band_pixels(monkeypatch, 1280, 800,
                 lambda x, y: (205, 205, 205) if 136 <= x < 186 and 50 <= y < 78 else None)
    assert fb.probe_location_switch("frame.png", 1280, 800) == ("unknown", None)


def test_location_probe_without_a_capture_is_unknown(monkeypatch):
    _band_pixels(monkeypatch, 1280, 800, lambda x, y: (233, 84, 32))
    assert fb.probe_location_switch(None, 1280, 800) == ("unknown", None)
TZ_ANR = ["Previous", "Time Zone", "Time Zone", TZ_BLURB, CITY,
          '"Initial Setup" Is Not Responding', "Force Quit", "Wait"]


def test_timezone_slow_commit_needs_no_recovery(tmp_path):
    # The commit takes two polls offline: the first re-observes still show
    # the time zone page, but the driver waits it out instead of declaring
    # the advance lost. No retype, no retry, no Previous click.
    frames = [TZ_FRESH, TZ_RESULTS, TZ_SELECTED, TZ_LOST, TZ_LOST, PRIVACY,
              COMPLETE, SESSION]
    result, evidence, typed, _ = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert evidence["timezone_city"] == CITY
    assert typed == ["london"]
    assert evidence.get("timezone_retries", 0) == 0
    assert "Previous" not in [c["label"] for c in evidence["clicks"]]


def test_timezone_stalled_advance_is_nudged_with_enter(tmp_path):
    # Run 42599329052: both legs sat 6+ min on a static selected page
    # after one Next click (London shown, Next unread, no spinner, no
    # ANR). The advance wait re-drives instead of watching passively:
    # Enter reaches the focused search entry when Next is unread, and
    # the guest then leaves the page. Two nudges over nine polls.
    frames = [TZ_FRESH, TZ_RESULTS, TZ_SELECTED] + [TZ_LOST] * 9 + [PRIVACY, COMPLETE, SESSION]
    result, evidence, _, keys = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert evidence.get("timezone_nudges") == 2
    assert keys.count("ret") == 2


def test_timezone_stalled_advance_reclicks_a_readable_next(tmp_path):
    # The Next button stays readable but the guest never advances: the
    # pointer and Enter already failed by the first two nudges, so the
    # cycle keeps trying keyboard actuators before the pointer comes
    # back around (run 42697802969 ignored a dozen pointer/Enter
    # re-drives on both legs). Three nudges over thirteen polls.
    stuck = TZ_LOST + ["Next"]
    frames = [TZ_FRESH, TZ_RESULTS, TZ_SELECTED] + [stuck] * 13 + [PRIVACY, COMPLETE, SESSION]
    result, evidence, _, keys = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert evidence.get("timezone_nudges") == 3
    assert keys == ["ret", "tab", "ret"]
    assert evidence.get("keys") == keys
    # The initial Next plus the one pointer re-click; the wait consumes
    # the following page, so the loop never clicks Next on it.
    assert [c["label"] for c in evidence["clicks"]].count("Next") == 2


def test_timezone_nudge_cycles_keyboard_focus(tmp_path):
    # Run 42697802969: Next unread, pointer and Enter ignored. The
    # cycle still reaches Tab plus Enter on the third nudge, so a page
    # that answers only key focus can advance. Three nudges over
    # thirteen polls.
    frames = [TZ_FRESH, TZ_RESULTS, TZ_SELECTED] + [TZ_LOST] * 13 + [PRIVACY, COMPLETE, SESSION]
    result, evidence, _, keys = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert evidence.get("timezone_nudges") == 3
    assert keys == ["ret", "tab", "ret", "ret"]
    assert evidence.get("keys") == keys


def test_timezone_true_loss_steps_back_and_redrives(tmp_path):
    # The commit never lands (20 polls of the lost page, 4 ignored
    # nudges): the driver steps back with Previous, comes forward onto a
    # fresh page, and drives the first-time path again to Setup Complete.
    # One retype, one retry.
    frames = ([TZ_FRESH, TZ_RESULTS, TZ_SELECTED] + [TZ_LOST] * 20
              + [TZ_HELP, TZ_HELP]
              + [TZ_FRESH, TZ_RESULTS, TZ_SELECTED, PRIVACY, COMPLETE, SESSION])
    result, evidence, typed, _ = run("setup", frames, tmp_path)
    assert result == 0 and evidence["completed"] is True
    assert evidence["timezone_city"] == CITY
    assert typed == ["london", "london"]
    assert evidence.get("timezone_retries") == 1
    assert evidence.get("timezone_nudges") == 4
    assert [c["label"] for c in evidence["clicks"]].count("Previous") == 1


def test_timezone_redos_stay_bounded(tmp_path):
    # The guest keeps returning the displayed-but-lost page through every
    # Previous cycle: the third redo raises instead of clicking forever.
    # Each 20-poll wait fires 4 ignored nudges first.
    frames = (([TZ_FRESH, TZ_RESULTS, TZ_SELECTED] + [TZ_LOST] * 20
               + [TZ_HELP, TZ_HELP]) * 2
              + [TZ_FRESH, TZ_RESULTS, TZ_SELECTED] + [TZ_LOST] * 20 + [TZ_LOST])
    result, evidence, typed, _ = run("setup", frames, tmp_path)
    assert result == 1 and evidence["completed"] is False
    assert evidence["error"] == "time zone city not accepted"
    assert typed == ["london", "london", "london"]
    assert evidence.get("timezone_retries") == 3
    assert evidence.get("timezone_nudges") == 12


def test_timezone_hang_aborts_the_commit_wait(tmp_path):
    # The shell reports Initial Setup hung mid-commit: the wait raises at
    # once with the dialog as the evidence instead of burning its polls.
    frames = [TZ_FRESH, TZ_RESULTS, TZ_SELECTED, TZ_LOST, TZ_ANR]
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 1 and evidence["completed"] is False
    assert evidence["error"] == "initial setup stopped responding during the time-zone commit"


def test_timezone_hang_fails_closed_at_loop_top(tmp_path):
    # The hung page is returned outside the time-zone waits (here on the
    # account page): the loop-top guard fails closed before any click
    # lands on the dead app.
    about_hung = ABOUT + ['"Initial Setup" Is Not Responding', "Force Quit", "Wait"]
    frames = [WELCOME, WELCOME, TYPING, PRIVACY, about_hung]
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 1 and evidence["completed"] is False
    assert evidence["error"] == "initial setup stopped responding"


def test_timezone_hang_aborts_the_step_back(tmp_path):
    # The step back lands on the hung page: the settled wait raises at once
    # instead of trusting transitional frames around the dialog. The
    # 20-poll advance wait must first burn out on the lost page.
    frames = ([TZ_FRESH, TZ_RESULTS, TZ_SELECTED] + [TZ_LOST] * 20 + [TZ_LOST]
              + [TZ_LOST, TZ_ANR])
    result, evidence, _, _ = run("setup", frames, tmp_path)
    assert result == 1 and evidence["completed"] is False
    assert evidence["error"] == "initial setup stopped responding on the step back from the lost time zone"


def test_echo_last_frames_prints_public_text_only(capsys):
    frames = [
        {'file': 'a.png', 'state': 'unknown', 'text': ['old']},
        {'state': 'greeter-password', 'private': True},
        {'file': 'b.png', 'state': 'unknown', 'text': ['Activities', 'Tue 01:30']},
        {'file': 'c.png', 'state': 'unknown', 'text': ['Sorry, that didn\'t work']},
    ]
    fb.echo_last_frames(frames, count=2)
    out = capsys.readouterr().out.splitlines()
    assert out == [
        '# last frame b.png state=unknown: Activities | Tue 01:30',
        "# last frame c.png state=unknown: Sorry, that didn't work",
    ]


def test_installer_driver_echo_last_frames_skips_private(capsys):
    from lib import gnome_installer_driver as gid
    gid.echo_last_frames([{'file': 'w.png', 'state': 'unknown', 'text': ['Welcome to', 'Sailfin']},
                          {'state': 'password', 'private': True}])
    assert capsys.readouterr().out == '# last frame w.png state=unknown: Welcome to | Sailfin\n'


BLANK = ["Display output is not active."]


def test_login_wakes_a_blanked_display_then_proves_the_session(tmp_path):
    result, evidence, typed, keys = run("login", [GREETER, BLANK, BLANK, SESSION], tmp_path)
    assert result == 0
    assert evidence["display_wakes"] == 2
    assert typed == [PASSWORD]
    assert keys.count("shift") == 2


def test_login_still_fails_closed_when_the_display_never_wakes(tmp_path):
    result, evidence, _, _ = run("login", [GREETER] + [BLANK] * 40, tmp_path)
    assert result == 1 and evidence["completed"] is False
    assert evidence["display_wakes"] == 40
