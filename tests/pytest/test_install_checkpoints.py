#!/usr/bin/env python3
"""Tests for scripts/install-checkpoints.py — the screen-checkpoint OCR gate.

Synthesises evidence directories with real rendered text (ImageMagick) and
runs the real script over them, so the assertions exercise the actual OCR
path rather than a stubbed one. A contract that is only ever tested against
mocked text would not catch the thing it exists to catch: keywords that no
OCR pass can actually read off a framebuffer.

Skipped wholesale when ImageMagick or tesseract is absent — a missing tool is
a fact about the host, and turning it into a red test would only train people
to ignore this file.

Run with: pytest tests/pytest/test_install_checkpoints.py -v
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "scripts", "install-checkpoints.py")

IM = (["magick"] if shutil.which("magick")
      else ["convert"] if shutil.which("convert") else None)
HAVE_TESSERACT = shutil.which("tesseract") is not None


def _find_font():
    """A concrete TTF path for -annotate.

    ImageMagick resolves font *names* through its own type map, which a
    Homebrew build on an atomic desktop does not have: every -annotate there
    fails with "unable to read font ''". Naming a file skips the type map
    entirely, so the test renders the same on a runner and on a workstation.
    """
    candidates = [
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/liberation-fonts/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    for root, _dirs, files in os.walk("/usr/share/fonts"):
        for name in sorted(files):
            # Emoji fonts render every glyph as a picture; tesseract reads
            # nothing off them.
            if name.endswith(".ttf") and "Emoji" not in name:
                return os.path.join(root, name)
    return None


FONT = _find_font()

pytestmark = pytest.mark.skipif(
    IM is None or not HAVE_TESSERACT or FONT is None,
    reason="needs ImageMagick, tesseract and a TTF to render and read frames")


def render(path, text, size="1280x800"):
    """Write a PNG of `text` big enough for tesseract to read reliably."""
    subprocess.run(
        IM + ["-size", size, "canvas:white", "-gravity", "center",
              "-font", FONT, "-pointsize", "48", "-fill", "black",
              "-annotate", "+0+0", text, path],
        check=True)


def blank(path, size="1280x800"):
    subprocess.run(IM + ["-size", size, "canvas:black", path], check=True)


def run(outdir, *args):
    r = subprocess.run(
        [sys.executable, SCRIPT, str(outdir), *args],
        capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def spec(tmp_path, body):
    p = tmp_path / "spec.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_matching_screen_passes(tmp_path):
    """A frame whose text matches the checkpoint's keywords is a pass."""
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "10-ready.png"), "Welcome to Marlin")
    s = spec(tmp_path, """
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["welcome"]
            forbid: ["kernel panic"]
        """)
    rc, log = run(out, "--spec", s, "--flavor", "kde")
    assert rc == 0, log
    assert "ok - [live-desktop] screen says one of" in log


def test_wrong_screen_fails_with_the_transcript(tmp_path):
    """A mismatch fails AND prints what was actually on screen.

    "matched nothing" alone is not diagnosable; the whole reason the OCR text
    is kept is so a failure says what the screen said instead.
    """
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "10-ready.png"), "Something Else Entirely")
    s = spec(tmp_path, """
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["welcome to"]
        """)
    rc, log = run(out, "--spec", s, "--flavor", "kde")
    assert rc == 1, log
    assert "not ok - [live-desktop] screen says one of" in log
    assert "something else" in log.lower()


def test_forbidden_text_fails_even_when_not_required(tmp_path):
    """A panic on an optional checkpoint is still a panic."""
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "30-installed.png"), "Kernel panic - not syncing")
    s = spec(tmp_path, """
        checkpoints:
          - id: installed-login
            phase: installed
            frames: ["30-installed"]
            required: false
            keywords: ["login"]
            forbid: ["kernel panic"]
        """)
    rc, log = run(out, "--spec", s, "--flavor", "kde")
    assert rc >= 1, log
    assert "not ok - [installed-login] screen free of failure text" in log


def test_blank_frame_fails_the_render_check(tmp_path):
    """A black screen is the failure a screenshot-only gate cannot see."""
    out = tmp_path / "evidence"
    out.mkdir()
    blank(str(out / "10-ready.png"))
    s = spec(tmp_path, """
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["welcome"]
        """)
    rc, log = run(out, "--spec", s, "--flavor", "kde")
    assert rc >= 1, log
    assert "not ok - [live-desktop] screen renders content" in log


def test_missing_frame_is_fatal_only_when_required(tmp_path):
    out = tmp_path / "evidence"
    out.mkdir()
    s = spec(tmp_path, """
        checkpoints:
          - id: optional-stage
            phase: installed
            frames: ["installed-tpm-autounlock"]
            required: false
            keywords: ["login"]
        """)
    rc, log = run(out, "--spec", s, "--flavor", "kde")
    assert rc == 0, log
    assert "not ok - [optional-stage] frame captured" in log


def test_per_desktop_keywords_override_the_default_list(tmp_path):
    """The five frontends are separate forks; each gets its own wording."""
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "10-ready.png"), "Select Target Disk")
    s = spec(tmp_path, """
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["a phrase no frame contains"]
            desktops:
              kde: ["select target disk"]
        """)
    assert run(out, "--spec", s, "--flavor", "kde")[0] == 0
    # gnome falls back to the default list, which this frame does not satisfy.
    assert run(out, "--spec", s, "--flavor", "gnome")[0] == 1


def test_flavor_family_strips_the_hardware_suffix(tmp_path):
    """kde-nvidia and kde-cachyos are KDE — the contract is per desktop."""
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "10-ready.png"), "Select Target Disk")
    s = spec(tmp_path, """
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["a phrase no frame contains"]
            desktops:
              kde: ["select target disk"]
        """)
    for flavor in ("kde-nvidia", "kde-cachyos", "kde-hwe"):
        assert run(out, "--spec", s, "--flavor", flavor)[0] == 0, flavor


def test_summary_json_records_every_checkpoint(tmp_path):
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "10-ready.png"), "Welcome to Marlin")
    s = spec(tmp_path, """
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["welcome"]
        """)
    run(out, "--spec", s, "--flavor", "kde", "--variant", "marlin")
    summary = json.loads((out / "install-checkpoints-kde.json").read_text())
    assert summary["variant"] == "marlin"
    assert summary["desktop"] == "kde"
    assert summary["failures"] == 0
    assert summary["checkpoints"][0]["id"] == "live-desktop"
    assert "welcome" in summary["checkpoints"][0]["matched"]


def test_phase_filter_narrows_the_run(tmp_path):
    """A boot-only run must not be failed for a missing installed-system frame."""
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "10-ready.png"), "Welcome to Marlin")
    s = spec(tmp_path, """
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["welcome"]
          - id: installed-login
            phase: installed
            frames: ["30-installed"]
            required: true
            keywords: ["password"]
        """)
    assert run(out, "--spec", s, "--flavor", "kde")[0] == 1
    assert run(out, "--spec", s, "--flavor", "kde", "--phase", "live")[0] == 0


def test_shipped_contract_parses_and_names_only_known_phases():
    """The real contract must load, and its phases must be ones the script
    accepts — a phase nothing emits is a checkpoint that silently never runs."""
    yaml = pytest.importorskip("yaml")
    path = os.path.join(REPO, "tests", "install-pipeline-screens.yaml")
    with open(path) as f:
        spec_doc = yaml.safe_load(f)
    checkpoints = spec_doc["checkpoints"]
    assert checkpoints, "contract has no checkpoints"
    for cp in checkpoints:
        assert cp["phase"] in ("live", "installed"), cp
        assert cp.get("frames"), cp
        keywords = [k for k in cp.get("keywords", [])]
        for per_desktop in (cp.get("desktops") or {}).values():
            keywords += per_desktop
        for kw in keywords:
            assert kw == kw.lower(), f"{cp['id']}: keywords are matched " \
                                     f"case-insensitively; keep them lowercase ({kw})"
            # Bare short tokens match OCR noise by accident — the rule
            # tests/installer-screens.yaml learned and this contract inherits.
            assert len(kw) >= 5, f"{cp['id']}: keyword {kw!r} is too short to " \
                                 f"survive OCR noise; use a heading or prompt"


def test_keyword_matches_when_ocr_drops_the_space(tmp_path):
    """MEASURED case: GDM's "Not listed?" comes back as "Notlisted?".

    A contract written in multi-word headings must survive tesseract joining
    two words, or it fails on screens it can plainly see.
    """
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "30-installed.png"), "Notlisted?")
    s = spec(tmp_path, """
        checkpoints:
          - id: installed-login
            phase: installed
            frames: ["30-installed"]
            required: true
            keywords: ["not listed"]
        """)
    rc, log = run(out, "--spec", s, "--flavor", "gnome")
    assert rc == 0, log


def test_despacing_does_not_match_a_different_screen(tmp_path):
    """Joining adjacent words must not let a keyword match unrelated text."""
    out = tmp_path / "evidence"
    out.mkdir()
    render(str(out / "30-installed.png"), "Restart Later")
    s = spec(tmp_path, """
        checkpoints:
          - id: installed-login
            phase: installed
            frames: ["30-installed"]
            required: true
            keywords: ["not listed"]
        """)
    assert run(out, "--spec", s, "--flavor", "gnome")[0] == 1


def test_smithay_desktops_are_not_failed_for_a_blank_frame_without_virgl(tmp_path):
    """cosmic/niri/xfce draw nothing without virgl — that is a host fact.

    Every CI runner lacks a render node, so enforcing the pixel assertions
    there would fail those cells forever for a reason that has nothing to do
    with the image.
    """
    out = tmp_path / "evidence"
    out.mkdir()
    blank(str(out / "10-ready.png"))
    s = spec(tmp_path, """
        needs_virgl: [cosmic, niri, xfce]
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["welcome"]
        """)
    rc, log = run(out, "--spec", s, "--flavor", "cosmic", "--no-gpu")
    assert rc == 0, log
    assert "not enforced" in log or "REPORTED" in log


def test_a_desktop_that_renders_without_virgl_still_fails_on_a_blank_frame(tmp_path):
    """The softening is per-desktop, not a blanket excuse.

    KDE composites fine under plain VGA, so a blank KDE frame is a real
    defect even on a host with no virgl.
    """
    out = tmp_path / "evidence"
    out.mkdir()
    blank(str(out / "10-ready.png"))
    s = spec(tmp_path, """
        needs_virgl: [cosmic, niri, xfce]
        checkpoints:
          - id: live-desktop
            phase: live
            frames: ["10-ready"]
            required: true
            keywords: ["welcome"]
        """)
    assert run(out, "--spec", s, "--flavor", "kde", "--no-gpu")[0] >= 1
