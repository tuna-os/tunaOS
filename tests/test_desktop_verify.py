#!/usr/bin/env python3
"""Unit tests for scripts/desktop-verify.py.

Covers the VLM desktop-verification script's core logic without any network:
  - _parse_results(): the Pass/Fail parsing contract (numbered lines, bare
    Result: lines, id-phrase matching, no-match -> None)
  - the check constant sets (ids unique, assertions present)
  - encode_image(): PNG round-trip + 1024px max-dimension resizing
  - call_gemini() / call_lemonade(): request shape + result parsing with a
    mocked HTTP layer, and lemonade's exception -> error-dict fallback
"""

import base64
import importlib.util
import io
from pathlib import Path

import pytest

# desktop-verify.py hard-exits (77) when Pillow/requests are absent; skip the
# whole module in CI environments that don't install them.
pytest.importorskip("PIL")
pytest.importorskip("requests")

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "desktop-verify.py"
_spec = importlib.util.spec_from_file_location("desktop_verify", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

CHECKS = _mod.DESKTOP_CHECKS  # boot-complete, compositor-active, no-crash


# ── _parse_results ───────────────────────────────────────────────────────────

class TestParseResults:
    def test_numbered_pass_lines(self):
        text = "\n".join(
            f"{i+1}. Result: Pass. Evidence: ok" for i in range(len(CHECKS))
        )
        r = _mod._parse_results(text, CHECKS)
        assert r["results"] == {c["id"]: True for c in CHECKS}
        assert r["raw"] == text

    def test_numbered_fail_on_first_check(self):
        text = (
            "1. Result: Fail. Evidence: text console\n"
            "2. Result: Pass. Evidence: ok\n"
            "3. Result: Pass. Evidence: ok"
        )
        r = _mod._parse_results(text, CHECKS)
        assert r["results"]["boot-complete"] is False
        assert r["results"]["compositor-active"] is True
        assert r["results"]["no-crash"] is True

    def test_bare_result_lines_fallback_uses_first_line(self):
        # Contract as implemented: the bare-"Result:" fallback loop breaks on
        # the FIRST "Result:" line, so every unmatched check inherits the
        # first line's verdict. Pinned here (quirk noted in the coverage
        # issue); the numbered/id-phrase paths are the precise ones.
        text = "Result: Pass\nResult: Fail\nResult: Pass"
        r = _mod._parse_results(text, CHECKS)
        assert r["results"] == {
            "boot-complete": True,
            "compositor-active": True,
            "no-crash": True,
        }

    def test_id_phrase_matching_is_case_insensitive(self):
        text = "boot complete: pass\ncompositor active: PASS\nno crash: fail"
        r = _mod._parse_results(text, CHECKS)
        assert r["results"] == {
            "boot-complete": True,
            "compositor-active": True,
            "no-crash": False,
        }

    def test_no_match_is_unknown(self):
        r = _mod._parse_results("the screen shows a kernel panic", CHECKS)
        assert r["results"] == {c["id"]: None for c in CHECKS}

    def test_empty_response_is_unknown(self):
        r = _mod._parse_results("", CHECKS)
        assert r["results"] == {c["id"]: None for c in CHECKS}


# ── check constants ──────────────────────────────────────────────────────────

class TestChecks:
    def test_all_ids_unique_and_assertions_present(self):
        all_checks = (
            _mod.DESKTOP_CHECKS + _mod.LOGIN_CHECKS + _mod.DESKTOP_SESSION_CHECKS
        )
        ids = [c["id"] for c in all_checks]
        assert len(ids) == len(set(ids)), f"duplicate check ids: {ids}"
        for c in all_checks:
            assert c["id"] and c["assertion"], f"empty check: {c!r}"

    def test_expected_screen_coverage(self):
        ids = {c["id"] for c in _mod.DESKTOP_CHECKS + _mod.LOGIN_CHECKS + _mod.DESKTOP_SESSION_CHECKS}
        assert ids == {
            "boot-complete", "compositor-active", "no-crash",
            "login-prompt", "desktop-loaded", "apps-available",
        }


# ── encode_image ─────────────────────────────────────────────────────────────

class TestEncodeImage:
    def _make_png(self, size, color=(40, 80, 120)):
        from PIL import Image
        img = Image.new("RGB", size, color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_encodes_png(self, tmp_path):
        p = tmp_path / "shot.png"
        p.write_bytes(self._make_png((64, 64)))
        b64 = _mod.encode_image(str(p))
        raw = base64.b64decode(b64)
        assert raw[:8] == b"\x89PNG\r\n\x1a\n", "output is not a PNG"

    def test_large_image_resized_to_1024(self, tmp_path):
        from PIL import Image
        p = tmp_path / "big.png"
        p.write_bytes(self._make_png((2048, 1024)))
        b64 = _mod.encode_image(str(p))
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        assert max(img.size) <= 1024, f"resized image still {img.size}"

    def test_small_image_not_upscaled(self, tmp_path):
        from PIL import Image
        p = tmp_path / "small.png"
        p.write_bytes(self._make_png((200, 100)))
        b64 = _mod.encode_image(str(p))
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        assert img.size == (200, 100), f"small image resized to {img.size}"


# ── call_gemini / call_lemonade ──────────────────────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestCallGemini:
    def test_posts_and_parses(self, monkeypatch):
        calls = {}

        def fake_post(url, **kw):
            calls["url"] = url
            calls["kw"] = kw
            return _FakeResp({
                "candidates": [{
                    "content": {"parts": [{"text":
                        "1. Result: Pass. Evidence: ok\n"
                        "2. Result: Pass. Evidence: ok\n"
                        "3. Result: Pass. Evidence: ok"}]}
                }]
            })

        monkeypatch.setattr(_mod.requests, "post", fake_post)
        r = _mod.call_gemini("aGVsbG8=", CHECKS, "test-key")
        assert all(v is True for v in r["results"].values())
        assert calls["kw"]["params"] == {"key": "test-key"}
        assert calls["kw"]["json"]["contents"][0]["parts"][0]["inline_data"]["data"] == "aGVsbG8="

    def test_prompt_contains_assertions(self, monkeypatch):
        seen = {}

        def fake_post(url, **kw):
            seen["prompt"] = kw["json"]["contents"][0]["parts"][1]["text"]
            return _FakeResp({"candidates": [{"content": {"parts": [{"text": ""}]}}]})

        monkeypatch.setattr(_mod.requests, "post", fake_post)
        _mod.call_gemini("b3du", CHECKS, "k")
        assert CHECKS[0]["assertion"] in seen["prompt"]
        assert "Result: Pass. Evidence:" in seen["prompt"]


class TestCallLemonade:
    def test_posts_openai_shape_and_parses(self, monkeypatch):
        seen = {}

        def fake_post(url, **kw):
            seen["url"] = url
            seen["json"] = kw["json"]
            return _FakeResp({"choices": [{"message": {"content":
                "1. Result: Pass. Evidence: ok\n"
                "2. Result: Fail. Evidence: console\n"
                "3. Result: Pass. Evidence: ok"}}]})

        monkeypatch.setattr(_mod.requests, "post", fake_post)
        r = _mod.call_lemonade("aGVsbG8=", CHECKS)
        assert r["results"]["boot-complete"] is True
        assert r["results"]["compositor-active"] is False
        assert r["results"]["no-crash"] is True
        assert seen["json"]["messages"][0]["content"][0]["type"] == "image_url"

    def test_exception_returns_error_dict(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError("no lemonade")

        monkeypatch.setattr(_mod.requests, "post", boom)
        r = _mod.call_lemonade("aGVsbG8=", CHECKS)
        assert "error" in r
        assert all(v is False for v in r["results"].values())
