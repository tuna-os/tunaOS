#!/usr/bin/env python3
"""Unit tests for scripts/import-frontend-parity.py.

Covers the parity-matrix importer's pure logic:
  - cell(): the ⬜/✅ᶜ/❌ᶜ/⬜ᶜ cell semantics (required vs optional screens)
  - gh(): subprocess wrapper degradation to _Failed when gh is absent
  - fetch(): run-list filtering (main branch only), download fallback
    across runs, missing-file handling, JSON errors
  - render(): the generated matrix block, incl. unfetched-frontend rows
"""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "import-frontend-parity.py"
_spec = importlib.util.spec_from_file_location("import_frontend_parity", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ── cell() ───────────────────────────────────────────────────────────────────

class TestCell:
    def test_unreached_screen_is_blank(self):
        assert _mod.cell({"screens": {"welcome": None}}, "welcome") == "⬜"

    def test_screen_missing_from_data_is_blank(self):
        assert _mod.cell({"screens": {}}, "welcome") == "⬜"

    def test_reached_screen_is_capture_pass(self):
        assert _mod.cell({"screens": {"welcome": True}}, "welcome") == "✅ᶜ"

    def test_required_screen_miss_is_error(self):
        # welcome/disk/summary are REQUIRED — a miss is a real gap.
        assert _mod.cell({"screens": {"welcome": False}}, "welcome") == "❌ᶜ"
        assert _mod.cell({"screens": {"disk": False}}, "disk") == "❌ᶜ"
        assert _mod.cell({"screens": {"summary": False}}, "summary") == "❌ᶜ"

    def test_optional_screen_miss_is_blank_capture(self):
        # install/done are not required — a miss is only a capture gap.
        assert _mod.cell({"screens": {"install": False}}, "install") == "⬜ᶜ"
        assert _mod.cell({"screens": {"done": False}}, "done") == "⬜ᶜ"


# ── gh() ─────────────────────────────────────────────────────────────────────

class TestGh:
    def test_passes_through_completed_process(self, monkeypatch):
        fake = subprocess.CompletedProcess([], 0, stdout="out", stderr="err")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
        assert _mod.gh("run", "list") is fake

    def test_degrades_to_failed_when_gh_missing(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("no gh")

        monkeypatch.setattr(subprocess, "run", boom)
        r = _mod.gh("run", "list")
        assert r.returncode == 1
        assert "gh CLI not found" in r.stderr


# ── fetch() ──────────────────────────────────────────────────────────────────

class TestFetch:
    def _fetch(self, monkeypatch, tmp_path, gh_side_effect):
        calls = []

        def fake_gh(*args, **kw):
            calls.append((args, kw))
            if callable(gh_side_effect):
                return gh_side_effect(args, kw, tmp_path)
            return gh_side_effect

        monkeypatch.setattr(_mod, "gh", fake_gh)
        return _mod.fetch("tuna-os/tuna-installer-kde", "kde", str(tmp_path)), calls

    def test_run_list_failure(self, monkeypatch, tmp_path):
        (data, reason), _ = self._fetch(
            monkeypatch, tmp_path,
            lambda args, kw, tmp: subprocess.CompletedProcess([], 1, stdout="", stderr="boom"))
        assert data is None
        assert "gh run list failed" in reason

    def test_only_main_branch_runs_count(self, monkeypatch, tmp_path):
        body = json.dumps([
            {"databaseId": 1, "conclusion": "success", "headBranch": "feature/x"},
            {"databaseId": 2, "conclusion": "success", "headBranch": "main"},
        ])

        def fake_gh(args, kw, tmp):
            if args[1] == "list":
                return subprocess.CompletedProcess([], 0, stdout=body, stderr="")
            # download: simulate failure for run 2, so we exhaust runs.
            return subprocess.CompletedProcess([], 1, stdout="", stderr="dl failed")

        (data, reason), calls = self._fetch(monkeypatch, tmp_path, fake_gh)
        assert data is None
        assert "no run carried a parity report" in reason
        # Only the main-branch run was attempted for download.
        downloaded = [c for c in calls if c[0][1] == "download"]
        assert len(downloaded) == 1 and downloaded[0][0][2] == "2"

    def test_download_ok_but_report_missing(self, monkeypatch, tmp_path):
        body = json.dumps([{"databaseId": 7, "conclusion": "success", "headBranch": "main", "url": "https://github.com/run/7"}])

        def fake_gh(args, kw, tmp):
            if args[1] == "list":
                return subprocess.CompletedProcess([], 0, stdout=body, stderr="")
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        (data, reason), _ = self._fetch(monkeypatch, tmp_path, fake_gh)
        assert data is None
        assert "no run carried a parity report" in reason

    def test_success_returns_data_and_url(self, monkeypatch, tmp_path):
        body = json.dumps([{"databaseId": 9, "conclusion": "success", "headBranch": "main", "url": "https://github.com/run/9"}])

        def fake_gh(args, kw, tmp):
            if args[1] == "list":
                return subprocess.CompletedProcess([], 0, stdout=body, stderr="")
            # Simulate the workflow artifact layout under dest/<runid>/.
            out = os.path.join(str(tmp), str(args[2]))
            Path(out).mkdir(parents=True)
            Path(out, "walkthrough-kde.json").write_text(
                json.dumps({"screens": {"welcome": True}, "frames": 5}))
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        (data, url), _ = self._fetch(monkeypatch, tmp_path, fake_gh)
        assert data == {"screens": {"welcome": True}, "frames": 5}
        assert url == "https://github.com/run/9"

    def test_malformed_gh_json(self, monkeypatch, tmp_path):
        (data, reason), _ = self._fetch(
            monkeypatch, tmp_path,
            lambda args, kw, tmp: subprocess.CompletedProcess([], 0, stdout="{not json", stderr=""))
        assert data is None
        assert "could not parse gh output" in reason


# ── render() ─────────────────────────────────────────────────────────────────

class TestRender:
    def test_successful_and_unfetched_rows(self):
        results = {
            "kde": ({"screens": {"welcome": True, "disk": False, "summary": True},
                     "frames": 4, "rendered_frames": 4, "advanced_transitions": 3},
                    "https://github.com/run/9"),
            "cosmic": (None, "gh run list failed: boom"),
        }
        # fill the remaining frontends as unfetched
        for flavor in ("niri", "xfce"):
            results[flavor] = (None, "no runs on main")

        out = _mod.render(results)
        assert _mod.BEGIN in out and _mod.END in out
        assert "| Frontend | Source | welcome | disk | encryption | summary | install | done |" in out
        # KDE row: capture-pass welcome, capture-gap disk (optional? no —
        # disk is REQUIRED so a miss renders ❌ᶜ), pass summary.
        assert "[capture](https://github.com/run/9)" in out
        assert "✅ᶜ" in out
        assert "❌ᶜ" in out
        # Unfetched frontend renders all-blank cells and a note.
        assert "| Niri | — | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |" in out
        assert "- **Niri** — no parity report imported (no runs on main)." in out
        # The scope caveat stays in the block.
        assert "It attests to screen parity only." in out

    def test_capture_pass_does_not_claim_launch(self):
        results = {f: (None, "x") for _, f, _ in _mod.FRONTENDS}
        out = _mod.render(results)
        # Blank rows must not carry the capture-pass mark.
        assert "✅ᶜ" not in out
