"""A contract that could not see the screen it was pointed at.

`tests/installer-screens.yaml` says a welcome screen is one whose text
contains "welcome", "get started", "let's get" or "begin". Four of the five
frontends satisfy that. KDE's welcome page says none of them: its heading is

    text: "Install " + InstallerController.productName
                    -- tuna-installer-kde modules/welcome/.../main.qml:39

its body is "This wizard will guide you through installing <product> onto this
computer.", and its primary button is "Next" (src/qml/Wizard.qml:290).

So run 32718219267 reported all six screens unreached for kde, with

    # DIAGNOSIS: kde -- no installer screen was ever detected

while the readiness stamp written by that same process, in that same guest,
read `window=ApplicationWindow signal=frame-swapped page=welcome`. The
installer was up and on its welcome page. Six red lines, a diagnosis pointing
at autostart, OOM-kills and missing GL paths, and a working frontend.

The keyword list was never measured -- the disk list was measured against the
frontends' real headings on 2026-08-07, this one was written from the premise
that a welcome screen says "welcome". These tests hold the two halves of the
fix in place: the measurement (KDE really does say none of the old keywords)
and the behaviour (the harness now credits KDE's welcome page).

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
KDE_WELCOME = (
    "Install Yellowfin This wizard will guide you through installing "
    "Yellowfin onto this computer. You will choose a target disk and how it "
    "should be encrypted. Everything after that is handled by the installer. "
    "Next"
)
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
    """KDE's welcome page contains not one of the four original keywords.

    Asserted directly, because it is the fact the whole change rests on. If a
    future edit to the KDE frontend makes one of them true, this test failing
    is the signal that the added keyword is no longer load-bearing -- not a
    reason to delete it, but a reason to re-measure.
    """
    lowered = KDE_WELCOME.lower()
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


def test_kde_welcome_is_now_credited():
    """The behaviour: run the harness on KDE's real text."""
    proc, summary = run_walkthrough(
        {"00": KDE_WELCOME, "01": DISK, "02": DISK},
    )
    assert summary is not None, proc.stdout + proc.stderr
    assert summary["screens"]["welcome"] is True, (
        summary["screens"], proc.stdout
    )


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
            {"00": KDE_WELCOME, "01": DISK, "02": DISK},
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
        assert "cause 6" in proc.stdout, proc.stdout

    def test_empty_ocr_is_reported_as_a_different_cause(self):
        """Text absent everywhere and text present but unmatched want
        opposite fixes, so they must not print the same thing."""
        proc, _ = run_walkthrough({"00": "", "01": "", "02": ""})
        assert "read NO text on any frame" in proc.stdout, proc.stdout
        assert "cause 6" not in proc.stdout, proc.stdout

    def test_it_stays_quiet_when_every_required_screen_was_found(self):
        """Quiet on a green leg, or it is noise on every run."""
        proc, summary = run_walkthrough(
            {"00": KDE_WELCOME, "01": "Select Target Disk",
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
            {"00": KDE_WELCOME, "01": "Select Target Disk",
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
