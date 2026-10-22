"""Unit tests for scripts/install-checkpoints.py.

The production script is used by the LUKS install gate. These tests exercise
its contract parsing, frame selection, OCR matching, and failure accounting
without requiring QEMU, ImageMagick, or Tesseract.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-checkpoints.py"
SPEC = importlib.util.spec_from_file_location("install_checkpoints", SCRIPT)
assert SPEC and SPEC.loader
CHECKPOINTS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKPOINTS
SPEC.loader.exec_module(CHECKPOINTS)


@pytest.fixture(autouse=True)
def reset_tap_state():
    """Each main() call starts with a fresh TAP result accumulator."""
    CHECKPOINTS._tap = []
    CHECKPOINTS._fails = 0
    yield
    CHECKPOINTS._tap = []
    CHECKPOINTS._fails = 0


@pytest.mark.parametrize(
    ("flavor", "expected"),
    [
        ("kde-nvidia", "kde"),
        ("GNOME-hwe", "gnome"),
        ("cosmic", "cosmic"),
        ("", "gnome"),
        ("unknown", "unknown"),
    ],
)
def test_desktop_family_strips_overlay_suffixes(flavor, expected):
    assert CHECKPOINTS.desktop_family(flavor) == expected


def test_normalize_and_despace_make_ocr_matching_whitespace_tolerant():
    text = "  Get\n\tStarted  "
    assert CHECKPOINTS.normalize(text) == " get started "
    assert CHECKPOINTS.despace(text) == "GetStarted"


def test_find_frames_prefers_nonempty_png(tmp_path, monkeypatch):
    png = tmp_path / "ready.png"
    ppm = tmp_path / "ready.ppm"
    png.write_bytes(b"png")
    ppm.write_bytes(b"ppm")
    monkeypatch.setattr(CHECKPOINTS, "IM", ["convert"])

    assert CHECKPOINTS.find_frames(str(tmp_path), "ready") == [str(png)]


def test_find_frames_converts_ppm_when_png_is_absent(tmp_path, monkeypatch):
    ppm = tmp_path / "ready.ppm"
    png = tmp_path / "ready.png"
    ppm.write_bytes(b"ppm")
    monkeypatch.setattr(CHECKPOINTS, "IM", ["convert"])

    def convert(command, **kwargs):
        assert command[:2] == ["convert", str(ppm)]
        Path(command[-1]).write_bytes(b"png")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(CHECKPOINTS.subprocess, "run", convert)
    assert CHECKPOINTS.find_frames(str(tmp_path), "ready") == [str(png)]


def test_find_frames_uses_nonempty_retry_captures(tmp_path, monkeypatch):
    (tmp_path / "ready-1.png").touch()
    retry = tmp_path / "ready-2.png"
    retry.write_bytes(b"retry")
    monkeypatch.setattr(CHECKPOINTS, "IM", None)

    assert CHECKPOINTS.find_frames(str(tmp_path), "ready") == [str(retry)]


def test_stddev_returns_measurement_and_sentinel_on_bad_tool_output(monkeypatch):
    monkeypatch.setattr(CHECKPOINTS, "IM", ["magick"])
    monkeypatch.setattr(
        CHECKPOINTS.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout="0.125\n"
        ),
    )
    assert CHECKPOINTS.stddev("frame.png") == pytest.approx(0.125)

    monkeypatch.setattr(
        CHECKPOINTS.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="bad"),
    )
    assert CHECKPOINTS.stddev("frame.png") == -1.0


def test_ocr_uses_fresh_cache_without_running_tesseract(tmp_path, monkeypatch):
    frame = tmp_path / "ready.png"
    cache = tmp_path / "ready.ocr.txt"
    frame.write_bytes(b"frame")
    cache.write_text("cached text")
    monkeypatch.setattr(CHECKPOINTS, "HAVE_OCR", True)
    monkeypatch.setattr(
        CHECKPOINTS.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("fresh OCR should not run for cached frame"),
    )

    assert CHECKPOINTS.ocr(str(frame)) == "cached text"


def test_tap_counts_only_enforced_failures():
    CHECKPOINTS.tap(False, "optional", enforced=False)
    CHECKPOINTS.tap(False, "required", enforced=True)

    assert CHECKPOINTS._fails == 1
    assert [item["enforced"] for item in CHECKPOINTS._tap] == [False, True]


def test_main_reports_required_and_optional_missing_frames(tmp_path, monkeypatch):
    spec = {
        "checkpoints": [
            {"id": "required", "phase": "live", "required": True, "frames": ["ready"]},
            {"id": "optional", "phase": "installed", "required": False, "frames": ["done"]},
        ]
    }
    monkeypatch.setattr(CHECKPOINTS, "load_spec", lambda path: spec)
    monkeypatch.setattr(CHECKPOINTS, "HAVE_OCR", False)
    monkeypatch.setattr(CHECKPOINTS, "IM", None)
    monkeypatch.setattr(CHECKPOINTS, "contact_sheet", lambda *args: False)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path)])

    assert CHECKPOINTS.main() == 1
    summary = json.loads((tmp_path / "install-checkpoints-gnome.json").read_text())
    assert summary["failures"] == 1
    assert [item["id"] for item in summary["checkpoints"]] == ["required", "optional"]


def test_main_matches_keywords_and_rejects_forbidden_text(tmp_path, monkeypatch):
    frame = tmp_path / "ready.png"
    frame.write_bytes(b"frame")
    spec = {
        "checkpoints": [
            {
                "id": "ready",
                "phase": "live",
                "required": True,
                "frames": ["ready"],
                "keywords": ["get started"],
                "forbid": ["emergency shell"],
                "match": "all",
            }
        ]
    }
    monkeypatch.setattr(CHECKPOINTS, "load_spec", lambda path: spec)
    monkeypatch.setattr(CHECKPOINTS, "HAVE_OCR", True)
    monkeypatch.setattr(CHECKPOINTS, "IM", None)
    monkeypatch.setattr(CHECKPOINTS, "stddev", lambda path: -1.0)
    monkeypatch.setattr(CHECKPOINTS, "ocr", lambda path: "Get\nStarted")
    monkeypatch.setattr(CHECKPOINTS, "contact_sheet", lambda *args: False)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path)])

    assert CHECKPOINTS.main() == 0
    summary = json.loads((tmp_path / "install-checkpoints-gnome.json").read_text())
    assert summary["checkpoints"][0]["matched"] == ["get started"]
    assert summary["checkpoints"][0]["forbidden"] == []

    CHECKPOINTS._tap = []
    CHECKPOINTS._fails = 0
    monkeypatch.setattr(CHECKPOINTS, "ocr", lambda path: "Get Started\nemergency shell")
    assert CHECKPOINTS.main() == 1
    summary = json.loads((tmp_path / "install-checkpoints-gnome.json").read_text())
    assert summary["checkpoints"][0]["forbidden"] == ["emergency shell"]


def test_main_does_not_enforce_pixel_or_keyword_checks_without_virgl(tmp_path, monkeypatch):
    frame = tmp_path / "ready.png"
    frame.write_bytes(b"frame")
    spec = {
        "needs_virgl": ["cosmic"],
        "checkpoints": [
            {
                "id": "ready",
                "phase": "live",
                "required": True,
                "frames": ["ready"],
                "keywords": ["missing text"],
                "forbid": [],
            }
        ],
    }
    monkeypatch.setattr(CHECKPOINTS, "load_spec", lambda path: spec)
    monkeypatch.setattr(CHECKPOINTS, "HAVE_OCR", True)
    monkeypatch.setattr(CHECKPOINTS, "IM", None)
    monkeypatch.setattr(CHECKPOINTS, "stddev", lambda path: 0.0)
    monkeypatch.setattr(CHECKPOINTS, "ocr", lambda path: "different text")
    monkeypatch.setattr(CHECKPOINTS, "contact_sheet", lambda *args: False)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), str(tmp_path), "--flavor", "cosmic", "--no-gpu"],
    )

    assert CHECKPOINTS.main() == 0
    summary = json.loads((tmp_path / "install-checkpoints-cosmic.json").read_text())
    assert summary["pixels_enforced"] is False
    assert summary["failures"] == 0
