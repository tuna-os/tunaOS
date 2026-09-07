"""The install screen, measured against what is on it before the log scrolls.

The `install` row of tests/installer-screens.yaml carries a 2026-08-07 note
that ZERO of the four forks matched it, and the fix chosen then was to match
the backend's own step lines -- "partitioning", "installing image" -- on the
reasoning that every frontend streams the same backend.

That covers the screen once fisherman has emitted a step. It does not cover
the screen the moment it opens, which is the state a harness screenshot
actually catches, and it is the state three of five frontends spend the whole
walkthrough in:

    gnome   "Installing", "0:00 elapsed"      progress.blp:189,229
    kde     "Installing <p> onto <d>. Do not power off the machine."
    cosmic  "Installing <p>" + "Do not power off the computer."
    niri    "Installing..."                   ui/installer.qml:422
    xfce    "Installing <p>" + a PIPELINE_STEPS label

"do not power off" is on kde and cosmic, on that screen and no other, and
carries no product name. gnome is left unmatched on purpose -- see the file's
comment -- because the alternatives are a bare word the header forbids and a
string whose visibility depends on the recipe.

Run against the harness, not grepped: the install screen is index 4 in the
spec, so a match confined to visual state 0 is discarded by design, and a
test that only checked the keyword list would miss that entirely.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_installer_walkthrough import run_walkthrough  # noqa: E402

SPEC = Path(__file__).resolve().parents[1] / "tests" / "installer-screens.yaml"

WELCOME = "Welcome to Yellowfin"
DISK = "Select Target Disk"

KDE_PROGRESS = ("Installing Yellowfin onto /dev/vda. Do not power off the "
                "machine.")
COSMIC_PROGRESS = "Installing Yellowfin Do not power off the computer."


def install_keywords() -> list[str]:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))["screens"]
    row = next(s for s in spec if s["id"] == "install")
    # Still advisory. This change records drift; it does not make a frontend
    # fail for wording, which is a separate decision nobody has taken.
    assert row["required"] is False, row
    return [k.lower() for k in row["keywords"]]


def test_the_added_keyword_carries_no_product_name():
    assert "do not power off" in install_keywords()
    for kw in install_keywords():
        for banned in ("tunaos", "yellowfin", "skipjack", "bluefin"):
            assert banned not in kw, kw


def test_kdes_progress_screen_is_now_credited():
    proc, summary = run_walkthrough(
        {"00": WELCOME, "01": KDE_PROGRESS, "02": KDE_PROGRESS},
    )
    assert summary is not None, proc.stdout + proc.stderr
    assert summary["screens"]["install"] is True, (summary["screens"],
                                                   proc.stdout)


def test_cosmics_progress_screen_is_now_credited():
    proc, summary = run_walkthrough(
        {"00": WELCOME, "01": COSMIC_PROGRESS, "02": COSMIC_PROGRESS},
        flavor="cosmic",
    )
    assert summary is not None, proc.stdout + proc.stderr
    assert summary["screens"]["install"] is True, (summary["screens"],
                                                   proc.stdout)


def test_it_does_not_credit_an_install_to_a_disk_screen():
    """The phantom-row failure this list's comments are entirely about.

    Run 29681255102 credited 'install' to Select Target Disk off a single
    "%". A keyword added years later must not reopen that.
    """
    proc, summary = run_walkthrough(
        {"00": WELCOME, "01": DISK, "02": "Choose the disk where Yellowfin "
                                          "will be installed."},
    )
    assert summary is not None, proc.stdout + proc.stderr
    assert summary["screens"]["install"] is False, proc.stdout
    assert summary["screens"]["disk"] is True, proc.stdout


def test_the_added_keyword_is_what_does_the_work():
    """Mutation, with the substitution asserted before it is trusted."""
    original = SPEC.read_text(encoding="utf-8")
    mutated = original.replace(
        '"installing image", "do not power off"]', '"installing image"]')
    assert mutated != original, "the mutation matched nothing; it proves nothing"
    try:
        SPEC.write_text(mutated, encoding="utf-8")
        proc, summary = run_walkthrough(
            {"00": WELCOME, "01": KDE_PROGRESS, "02": KDE_PROGRESS},
        )
        assert summary is not None, proc.stdout + proc.stderr
        assert summary["screens"]["install"] is False, (
            "kde matched without the added keyword, so it is not what fixed it"
        )
    finally:
        SPEC.write_text(original, encoding="utf-8")
