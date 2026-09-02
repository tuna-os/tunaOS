"""Unit tests for scripts/generate-boot-report.py — pure report logic.

The script talks to six GitHub APIs via the gh CLI in main(); the pure
functions (age_marker, status_emoji, render_combo_row, render_report,
Combo) are tested here with no network, no gh, and no display.

The module reads GITHUB_REPOSITORY at import time, so it is loaded via
importlib with the env var set — mirroring how tests/test_update_index.py
loads a hyphenated script name.
"""

import datetime as dt
import importlib.util
import os
import sys
from pathlib import Path

import pytest

# ── Module loading (env-first, hyphenated filename) ────────────────────

# Assigned, not setdefault -- see the note in tests/test_boot_report_gh.py.
# Under Actions GITHUB_REPOSITORY is already set, so setdefault silently hands
# the module the real repository instead of this fixture.
os.environ["GITHUB_REPOSITORY"] = "tuna-os/tunaos"
os.environ["REPORT_DATE"] = "2026-08-10"

_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "generate-boot-report.py"
_spec = importlib.util.spec_from_file_location("generate_boot_report", _SCRIPT)
_rep = importlib.util.module_from_spec(_spec)
sys.modules["generate_boot_report"] = _rep
_spec.loader.exec_module(_rep)

REPO_OWNER = _rep.REPO_OWNER
Combo = _rep.Combo
age_marker = _rep.age_marker
status_emoji = _rep.status_emoji
render_combo_row = _rep.render_combo_row
render_report = _rep.render_report
e2e_status_for = _rep.e2e_status_for


# ── age_marker ──────────────────────────────────────────────────────────

def _iso(days_ago: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()


def test_age_marker_missing_timestamp():
    assert age_marker(None) == ("❓", "never")
    assert age_marker("N/A") == ("❓", "never")


def test_age_marker_unparseable_timestamp():
    assert age_marker("not-a-date") == ("❓", "not-a-date")


def test_age_marker_fresh_within_seven_days():
    assert age_marker(_iso(3)) == ("✅", "3 days")


def test_age_marker_today_and_one_day():
    now = dt.datetime.now(dt.timezone.utc)
    assert age_marker((now - dt.timedelta(minutes=5)).isoformat()) == ("✅", "today")
    assert age_marker(_iso(1)) == ("✅", "1 day")


def test_age_marker_stale_band():
    assert age_marker(_iso(10)) == ("⚠️", "10 days")


def test_age_marker_very_stale():
    assert age_marker(_iso(40)) == ("❌", "40 days")


def test_age_marker_accepts_zulu_suffix():
    # GitHub API timestamps are RFC3339 with 'Z' — must parse like '+00:00'.
    ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat().replace("+00:00", "Z")
    assert age_marker(ts) == ("✅", "2 days")


# ── status_emoji ────────────────────────────────────────────────────────

def test_status_emoji_known_conclusions():
    assert status_emoji("success") == "✅"
    assert status_emoji("failure") == "❌"
    assert status_emoji("cancelled") == "⏹️"
    assert status_emoji("skipped") == "⏭️"
    assert status_emoji("timed_out") == "⌛"


def test_status_emoji_unknown_and_missing():
    assert status_emoji(None) == "❓"
    assert status_emoji("") == "❓"
    assert status_emoji("in_progress") == "❓"


def test_e2e_status_does_not_claim_unrun_matrix_cells(monkeypatch):
    run = {"id": 123, "conclusion": "success", "html_url": "https://github.com/run/123"}
    monkeypatch.setattr(_rep, "latest_workflow_run", lambda _workflow: run)
    _rep._E2E_JOBS_CACHE = {123: [{"name": "E2E yellowfin:gnome", "conclusion": "success"}]}

    assert e2e_status_for("yellowfin", "kde") is None


def test_e2e_status_uses_matching_matrix_cell(monkeypatch):
    run = {"id": 123, "conclusion": "success", "html_url": "https://github.com/run/123"}
    monkeypatch.setattr(_rep, "latest_workflow_run", lambda _workflow: run)
    _rep._E2E_JOBS_CACHE = {123: [{
        "name": "E2E yellowfin:gnome",
        "conclusion": "failure",
        "html_url": "https://github.com/job/456",
    }]}

    assert e2e_status_for("yellowfin", "gnome") == {
        "conclusion": "failure",
        "html_url": "https://github.com/job/456",
    }


# ── Combo ───────────────────────────────────────────────────────────────

def test_combo_key():
    c = Combo(variant="yellowfin", flavor="gnome", build_iso=True, build_qcow2=True)
    assert c.key == "yellowfin-gnome"


# ── render_combo_row ────────────────────────────────────────────────────

def _combo():
    return Combo(variant="yellowfin", flavor="gnome", build_iso=True, build_qcow2=True)


def _iso_info(**overrides):
    info = {
        "created": _iso(2),
        "url": "https://example.com/iso.png",
        "run_id": 424242,
    }
    info.update(overrides)
    return info


def test_render_combo_row_header_and_image_line():
    out = render_combo_row(
        _combo(),
        _iso_info(),
        _iso_info(url="https://example.com/qcow2.png"),
        iso_changed=True,
        qcow2_changed=False,
        build_run={"conclusion": "success", "html_url": "https://github.com/run/1"},
        e2e_run=None,
    )
    assert "## `yellowfin` / `gnome`" in out
    assert f"**Image:** `ghcr.io/{REPO_OWNER}/yellowfin:gnome`" in out
    assert "build ✅ ([run](https://github.com/run/1))" in out
    assert "e2e ❓" in out
    assert "| ISO Boot | QCOW2 Boot |" in out
    assert "✨ changed" in out
    assert "= same" in out
    assert "https://example.com/iso.png" in out


def test_render_combo_row_no_screenshots():
    out = render_combo_row(_combo(), None, None, None, None, None, None)
    assert "_no screenshots available for this combo_" in out
    assert "| ISO Boot | QCOW2 Boot |" not in out


# ── render_report ───────────────────────────────────────────────────────

def test_render_report_sections_and_wishlist():
    combos = [
        {"rendered": "R-FRESH", "stale": False},
        {"rendered": "R-STALE", "stale": True},
    ]
    wishlist = {"letters": ["pkg-a"], "tables": ["pkg-a", "pkg-b"]}
    out = render_report(combos, wishlist)

    assert "# 🖥️ Weekly Boot Screenshot Report" in out
    assert "## Fresh screenshots" in out
    assert "R-FRESH" in out
    assert "## ⚠️ Stale or missing screenshots" in out
    assert "R-STALE" in out
    assert "## 📦 EL10 packaging wishlist" in out
    assert "| `pkg-a` | letters, tables |" in out
    assert "| `pkg-b` | tables |" in out


def test_render_report_empty_inputs():
    out = render_report([], {})
    assert "# 🖥️ Weekly Boot Screenshot Report" in out
    assert "## Fresh screenshots" not in out
    assert "## ⚠️ Stale or missing screenshots" not in out
    assert "## 📦 EL10 packaging wishlist" not in out
    assert "## 🚀 Release ISOs" in out
