"""A contract that could not see the screen it was pointed at.

kde run 32718219267 scored all six screens unreached and printed

    # DIAGNOSIS: kde -- no installer screen was ever detected

while the readiness stamp written by that same process, in that same guest,
read `window=ApplicationWindow signal=frame-swapped page=welcome`. The
installer was up and on its welcome page. Six red lines, a diagnosis pointing
at autostart, OOM-kills and missing GL paths, and a working frontend.

The first explanation -- "KDE's welcome page contains none of the spec's
keywords" -- was true of the PAGE and false of the SCREEN. Its body copy
really does say none of "welcome", "get started", "let's get" or "begin"
(modules/welcome/contents/ui/main.qml:39,48,56, primary button "Next" at
Wizard.qml:290), but the wizard draws the step name "Welcome" as a 1.6x
heading above it (Wizard.qml:46,185), faded in at startup by a `running: true`
animation. So the word was on screen and the match still did not happen, and
WHY is not yet known.

What these tests do hold:

  * the measurement, scoped honestly -- KDE's welcome page body carries none
    of the four original keywords, so the screen was recognisable only by a
    heading that animates;
  * the coverage added for it -- "will guide you through", the orientation
    sentence KDE, niri and cosmic all put on the welcome page and nowhere
    else, giving the screen a second and independent phrase to be found by;
  * the diagnostic that will actually answer the open question -- the harness
    now prints the text OCR read, on any leg missing a required screen.

They RUN the harness rather than grepping the spec, because a keyword list
that parses is not a keyword list that matches.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_installer_walkthrough import run_walkthrough  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "tests" / "installer-screens.yaml"

# Verbatim from the frontends' sources, with the product name filled in the way
# the branding pipeline fills it. These are the strings OCR sees.
# The page body ONLY -- what modules/welcome/contents/ui/main.qml draws. The
# wizard's own "Welcome" heading is drawn by Wizard.qml above it and is kept
# out of this constant deliberately, so the tests below can say which half of
# the screen carries which evidence.
KDE_WELCOME_BODY = (
    "Install Yellowfin This wizard will guide you through installing "
    "Yellowfin onto this computer. You will choose a target disk and how it "
    "should be encrypted. Everything after that is handled by the installer. "
    "Next"
)
# The whole screen, heading included. This is what a screenshot contains.
KDE_WELCOME_FULL = "Welcome " + KDE_WELCOME_BODY
NIRI_WELCOME = (
    "Welcome to Yellowfin This wizard will guide you through installing "
    "Yellowfin onto your computer. Get Started"
)
COSMIC_WELCOME = (
    "Welcome. This assistant will guide you through installing Yellowfin onto "
    "this computer. Get started"
)
GNOME_WELCOME = "Welcome to Yellowfin Install Yellowfin Credits"
XFCE_WELCOME = "Welcome to Yellowfin"

DISK = "Select Target Disk"


def welcome_keywords() -> list[str]:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))["screens"]
    assert spec[0]["id"] == "welcome", spec[0]
    return [k.lower() for k in spec[0]["keywords"]]


def test_the_measurement_that_started_this():
    """KDE's welcome PAGE contains not one of the four original keywords.

    Scoped to the page body on purpose. The claim that KDE's welcome SCREEN
    said none of them was wrong -- the wizard heading above it is the literal
    word -- and this test is what keeps that correction from being lost: it
    asserts only what was actually measured in the page source.

    If a future edit to the KDE frontend puts one of the four into the body,
    this failing is the signal that the added keyword is no longer
    load-bearing -- a reason to re-measure, not to delete it.
    """
    lowered = KDE_WELCOME_BODY.lower()
    for old in ("welcome", "get started", "let's get", "begin"):
        assert old not in lowered, (
            f"{old!r} is on KDE's welcome page after all -- re-measure the "
            "spec against the frontends rather than trusting this file"
        )


def test_the_spec_still_forbids_a_bare_product_noun():
    """The added keyword must not smuggle the product name back in.

    Three keywords were removed from the disk and install lists precisely
    because they embedded "tunaos", which would have punished the branding
    fix. A keyword containing a product name is the same mistake.
    """
    for kw in welcome_keywords():
        for banned in ("tunaos", "yellowfin", "skipjack", "albacore",
                       "bonito", "bluefin"):
            assert banned not in kw, kw


def test_kdes_page_body_alone_is_now_enough():
    """The behaviour the added keyword buys.

    If the animated heading is missed -- for whatever reason run 32718219267
    missed it -- the body copy still identifies the screen.
    """
    proc, summary = run_walkthrough(
        {"00": KDE_WELCOME_BODY, "01": DISK, "02": DISK},
    )
    assert summary is not None, proc.stdout + proc.stderr
    assert summary["screens"]["welcome"] is True, (
        summary["screens"], proc.stdout
    )


def test_the_heading_would_always_have_matched():
    """The correction, asserted rather than only written down.

    KDE's wizard heading IS the literal word "welcome", so a frame that
    contains it matches on the ORIGINAL keyword list. That is why "the spec
    cannot describe KDE's welcome screen" does not explain the failing run,
    and why the cause is recorded as open instead of closed.
    """
    proc, summary = run_walkthrough(
        {"00": KDE_WELCOME_FULL, "01": DISK, "02": DISK},
    )
    assert summary is not None, proc.stdout + proc.stderr
    assert summary["screens"]["welcome"] is True, proc.stdout


def test_every_other_frontend_still_matches():
    """A keyword added for one fork must not cost another its match."""
    for name, text in (("niri", NIRI_WELCOME), ("cosmic", COSMIC_WELCOME),
                       ("gnome", GNOME_WELCOME), ("xfce", XFCE_WELCOME)):
        proc, summary = run_walkthrough(
            {"00": text, "01": DISK, "02": DISK}, flavor=name,
        )
        assert summary is not None, proc.stdout + proc.stderr
        assert summary["screens"]["welcome"] is True, (name, proc.stdout)


def test_a_screen_that_is_not_a_welcome_screen_still_does_not_match():
    """It must still be able to say no, or it credits every frame."""
    proc, summary = run_walkthrough(
        {"00": "greetd 09:41 Tuesday 24 August", "01": "", "02": ""},
    )
    assert summary is not None, proc.stdout + proc.stderr
    assert summary["screens"]["welcome"] is False, proc.stdout


def test_the_added_keyword_is_what_does_the_work():
    """Mutation: drop it from the list and KDE goes back to unmatched.

    Guarded by asserting the substitution actually applied -- a mutation that
    silently matches nothing "passes" and proves the opposite of what it
    claims, which this repository has now produced twice.
    """
    original = SPEC.read_text(encoding="utf-8")
    mutated = original.replace(
        '"begin",\n               "will guide you through"]', '"begin"]')
    assert mutated != original, "the mutation matched nothing; it proves nothing"
    try:
        SPEC.write_text(mutated, encoding="utf-8")
        proc, summary = run_walkthrough(
            {"00": KDE_WELCOME_BODY, "01": DISK, "02": DISK},
        )
        assert summary is not None, proc.stdout + proc.stderr
        assert summary["screens"]["welcome"] is False, (
            "KDE matched without the added keyword, so the keyword is not "
            "what fixed it"
        )
    finally:
        SPEC.write_text(original, encoding="utf-8")


class TestTheDiagnosisPrintsWhatItRead:
    """Cause 6 was missing from a list of five.

    Every cause the diagnosis named assumed the installer was not on screen.
    None of them was "it is on screen and the spec cannot describe it", which
    is the one that was true. Printing the OCR text tells the two apart in one
    line, without downloading an artifact.
    """

    def test_unmatched_text_is_printed(self):
        proc, _ = run_walkthrough(
            {"00": "Zork the Great Underground Empire",
             "01": "Zork the Great Underground Empire",
             "02": "Zork the Great Underground Empire"},
        )
        assert "what the OCR actually read" in proc.stdout, proc.stdout
        # ocr() lowercases what it reads, so the excerpt does too.
        assert "underground empire" in proc.stdout, proc.stdout
        # Real words, so it must reach cause 6 rather than the noise branch.
        assert "cause 6" in proc.stdout, proc.stdout
        assert "Those are NOT words" not in proc.stdout, proc.stdout

    def test_empty_ocr_is_reported_as_a_different_cause(self):
        """Text absent everywhere and text present but unmatched want
        opposite fixes, so they must not print the same thing."""
        proc, _ = run_walkthrough({"00": "", "01": "", "02": ""})
        assert "Those are NOT words" in proc.stdout, proc.stdout
        assert "cause 6" not in proc.stdout, proc.stdout

    def test_noise_is_not_reported_as_a_vocabulary_problem(self):
        """The exact output kde run 32735883406 produced.

        Four distinct visual states, nine frames above the blank threshold,
        and a readiness stamp saying the wizard was on screen -- and this is
        what tesseract returned:

            state 0: 1 ft
            state 1: hm
            state 2: i]

        The first version of the block asked `if any(_seen.values())`, so it
        printed those three fragments under a heading inviting the reader to
        go fix the keyword list. They are not a vocabulary problem. A
        truthiness test cannot tell noise from words; a score can.
        """
        proc, _ = run_walkthrough({"00": "1 ft", "01": "hm", "02": "i]"})
        assert "Those are NOT words" in proc.stdout, proc.stdout
        assert "cause 6" not in proc.stdout, proc.stdout
        # The noise itself is still printed -- it is the evidence.
        assert "1 ft" in proc.stdout, proc.stdout

    def test_the_noise_report_names_what_it_tried(self):
        """It must say which OCR pass won and how big the frame was, or the
        reader is back to guessing between "dark theme" and "too small"."""
        proc, _ = run_walkthrough({"00": "1 ft", "01": "hm", "02": "i]"})
        assert "Frame geometry" in proc.stdout, proc.stdout
        assert "best pass per frame" in proc.stdout, proc.stdout

    def test_a_negated_pass_can_win_and_is_named(self):
        """The dark-theme fallback, exercised rather than assumed.

        tesseract wants dark ink on light paper. gnome -- the only flavor
        that has ever scored screens -- defaults to Adwaita light, so
        "kde draws light text on a dark ground" is a live reading of the
        noise, and the harness has to be able to act on it.

        Here the plain pass returns noise and only the negated copy returns
        words. If the escalation works, the screen is credited AND the
        report says which pass won, because "psm6-negated won" is the
        finding, not an implementation detail.
        """
        proc, summary = run_walkthrough(
            {"00": "1 ft", "01": "hm", "02": "i]"},
            tess_neg={"00": KDE_WELCOME_FULL, "01": "Select Target Disk",
                      "02": "Confirm Installation"},
        )
        assert summary is not None, proc.stdout + proc.stderr
        assert summary["screens"]["welcome"] is True, (summary["screens"],
                                                       proc.stdout)
        assert summary["screens"]["disk"] is True, proc.stdout

    def test_without_the_negated_fallback_the_same_frames_stay_unread(self):
        """The other half: identical noise, no readable negated copy, and
        the run must still report unreadable rather than inventing a
        match."""
        proc, summary = run_walkthrough({"00": "1 ft", "01": "hm", "02": "i]"})
        assert summary["screens"]["welcome"] is False, proc.stdout
        assert "Those are NOT words" in proc.stdout, proc.stdout

    def test_the_negation_leaves_no_file_behind(self):
        """The first version wrote its temporary next to the frame and a
        stub bug dropped a file called "-negate" into the repo root. The
        negated copy must be cleaned up whatever the pass returns."""
        proc, _ = run_walkthrough(
            {"00": "1 ft", "01": "hm", "02": "i]"},
            tess_neg={"00": KDE_WELCOME_FULL, "01": DISK, "02": DISK},
        )
        assert not list(ROOT.glob("*negate*")), list(ROOT.glob("*negate*"))
        assert not list(ROOT.glob("**/*.neg.png")), "negated copies left behind"

    def test_a_frame_that_is_not_a_png_does_not_crash_the_diagnosis(self):
        """The stub writes PPM bytes into .png files, so the geometry read
        gets a file with no IHDR. A diagnostic that raised here would take
        out the run it was added to explain."""
        proc, _ = run_walkthrough({"00": "1 ft", "01": "hm", "02": "i]"})
        assert proc.returncode in (0, 1), proc.stderr
        assert "Traceback" not in proc.stderr, proc.stderr
        assert "?x?" in proc.stdout, proc.stdout

    def test_it_stays_quiet_when_every_required_screen_was_found(self):
        """Quiet on a green leg, or it is noise on every run."""
        proc, summary = run_walkthrough(
            {"00": KDE_WELCOME_BODY, "01": "Select Target Disk",
             "02": "Confirm Installation"},
        )
        for req in ("welcome", "disk", "summary"):
            assert summary["screens"][req] is True, (req, proc.stdout)
        assert "what the OCR actually read" not in proc.stdout, proc.stdout

    def test_a_partial_match_still_prints_the_text(self):
        """The shape kde is expected to land in next: welcome credited, the
        later screens missing.

        Gated on a MISSING REQUIRED SCREEN rather than on "nothing matched
        at all" for exactly this case -- a diagnostic that only fires when
        the score is zero would go silent the moment the first keyword was
        fixed, which is when the remaining words on the page start to
        matter."""
        proc, summary = run_walkthrough(
            {"00": KDE_WELCOME_BODY, "01": "Select Target Disk",
             "02": "Select Target Disk"},
        )
        assert summary["screens"]["welcome"] is True, proc.stdout
        assert summary["screens"]["summary"] is False, proc.stdout
        assert "what the OCR actually read" in proc.stdout, proc.stdout
        assert "missing required: summary" in proc.stdout, proc.stdout

    def test_the_excerpt_is_bounded(self):
        """A diagnostic on an error path must stay cheap to print."""
        proc, _ = run_walkthrough({"00": "Q" * 5000, "01": "Q" * 5000,
                                   "02": "Q" * 5000})
        for line in proc.stdout.splitlines():
            if re.match(r"\s*#\s+state \d+:", line):
                assert len(line) < 260, len(line)
