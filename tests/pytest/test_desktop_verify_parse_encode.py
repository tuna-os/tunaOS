#!/usr/bin/env python3
"""Unit tests for scripts/desktop-verify.py

Tests the VLM response parser (_parse_results) and image encoder
(encode_image). No network calls or real VLM backends are used.

Run with: pytest tests/pytest/test_desktop_verify.py -v
"""

import base64
import io
import sys
import pathlib

import pytest

# ── Import testable functions from the script ────────────────────────────────
# The script isn't structured as a module, so we replicate/import the key
# logic here for testing.  Pillow + requests are module-level try/except
# guarded in the original (exit 77 without them); we gate the import here
# with pytest.importorskip.

PIL = pytest.importorskip("PIL", reason="requires Pillow")
requests = pytest.importorskip("requests", reason="requires requests")
from PIL import Image

# Add the scripts directory so we can import the module directly
_scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_scripts_dir))

import importlib

_desktop_verify = importlib.import_module("desktop-verify")
_parse_results = _desktop_verify._parse_results
encode_image = _desktop_verify.encode_image
DESKTOP_CHECKS = _desktop_verify.DESKTOP_CHECKS
LOGIN_CHECKS = _desktop_verify.LOGIN_CHECKS
DESKTOP_SESSION_CHECKS = _desktop_verify.DESKTOP_SESSION_CHECKS


# ── Helpers ──────────────────────────────────────────────────────────────────

def _checks(*groups):
    """Flatten one or more check lists into a single list."""
    result = []
    for g in groups:
        result.extend(g)
    return result


def _make_checks(n):
    """Build n synthetic checks with ids check-0, check-1, ..."""
    return [{"id": f"check-{i}", "assertion": f"Assertion {i}"} for i in range(n)]


# ── Test: _parse_results — numbered lines ───────────────────────────────────


class TestParseResultsNumbered:
    """Tests for VLM responses with numbered Result lines."""

    def test_all_pass_numbered(self):
        text = (
            "1. Result: Pass. Evidence: desktop visible.\n"
            "2. Result: Pass. Evidence: compositor active.\n"
            "3. Result: Pass. Evidence: no errors.\n"
        )
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["results"]["boot-complete"] is True
        assert result["results"]["compositor-active"] is True
        assert result["results"]["no-crash"] is True

    def test_all_fail_numbered(self):
        text = (
            "1. Result: Fail. Evidence: black screen.\n"
            "2. Result: Fail. Evidence: text console.\n"
            "3. Result: Fail. Evidence: crash dialog.\n"
        )
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["results"]["boot-complete"] is False
        assert result["results"]["compositor-active"] is False
        assert result["results"]["no-crash"] is False

    def test_mixed_pass_fail_numbered(self):
        text = (
            "1. Result: Pass. Evidence: OK.\n"
            "2. Result: Fail. Evidence: not graphical.\n"
            "3. Result: Pass. Evidence: clean.\n"
        )
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["results"]["boot-complete"] is True
        assert result["results"]["compositor-active"] is False
        assert result["results"]["no-crash"] is True

    def test_five_checks_numbered(self):
        checks = _make_checks(5)
        lines = [f"{i+1}. Result: {'Pass' if i % 2 == 0 else 'Fail'}." for i in range(5)]
        text = "\n".join(lines)
        result = _parse_results(text, checks)
        for i in range(5):
            expected = True if i % 2 == 0 else False
            assert result["results"][f"check-{i}"] is expected


# ── Test: _parse_results — id-phrase matching (case-insensitive) ────────────


class TestParseResultsIdMatching:
    """Tests for per-check id-phrase matching in VLM lines."""

    def test_id_phrase_match_with_spaces(self):
        """'boot complete' matches check id 'boot-complete' (dashes→spaces)."""
        text = "boot complete: Pass. System booted."
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["results"]["boot-complete"] is True

    def test_id_phrase_case_insensitive(self):
        text = "BOOT COMPLETE: Pass. System booted."
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["results"]["boot-complete"] is True

    def test_id_phrase_mixed_case(self):
        text = "Compositor Active: Fail. Showing text console."
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["results"]["compositor-active"] is False

    def test_id_phrase_in_longer_line(self):
        text = "The boot complete check shows Pass because the desktop loaded."
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["results"]["boot-complete"] is True

    def test_id_phrase_no_crash(self):
        text = "No crash detected. Result: Pass."
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["results"]["no-crash"] is True


# ── Test: _parse_results — bare Result: fallback ─────────────────────────────


class TestParseResultsFallback:
    """Tests for the bare 'Result:' prefix fallback behavior.

    Quirk (GH #1393): the fallback loop breaks on the *first* `Result:` line,
    so an unnumbered multi-line response like:
        Result: Pass
        Result: Fail
    makes every unmatched check inherit the first line's verdict.
    We pin this current behavior with a comment noting the quirk.
    """

    def test_fallback_single_result_pass(self):
        """Single bare Result: Pass — all checks get True via fallback."""
        text = "Result: Pass"
        checks = _make_checks(3)
        result = _parse_results(text, checks)
        # Fallback hits first Result: line, all checks inherit Pass
        for c in checks:
            assert result["results"][c["id"]] is True

    def test_fallback_single_result_fail(self):
        text = "Result: Fail"
        checks = _make_checks(2)
        result = _parse_results(text, checks)
        for c in checks:
            assert result["results"][c["id"]] is False

    def test_fallback_quirk_first_line_wins(self):
        """Quirk: bare Result: fallback uses only the FIRST Result: line.
        Second Result: line is ignored for unmatched checks."""
        text = "Result: Pass\nResult: Fail\nResult: Fail"
        checks = _make_checks(3)
        result = _parse_results(text, checks)
        # All 3 checks fall through to fallback, which hits first Result: Pass
        for c in checks:
            assert result["results"][c["id"]] is True

    def test_fallback_with_numbered_mixed(self):
        """Numbered line matches check-0; checks 1 and 2 fall back."""
        text = (
            "1. boot complete: Pass. Desktop visible.\n"
            "Result: Fail"
        )
        result = _parse_results(text, DESKTOP_CHECKS)
        # check-0 matched by id phrase
        assert result["results"]["boot-complete"] is True
        # checks 1,2 fall back to first Result: line
        assert result["results"]["compositor-active"] is False
        assert result["results"]["no-crash"] is False

    def test_fallback_with_pass_period(self):
        """'Pass.' (with period) is also recognized in the primary loop."""
        text = "1. Pass."
        checks = _make_checks(1)
        result = _parse_results(text, checks)
        assert result["results"]["check-0"] is True


# ── Test: _parse_results — edge cases ────────────────────────────────────────


class TestParseResultsEdgeCases:
    """Edge cases for _parse_results."""

    def test_empty_text_returns_none_for_all(self):
        result = _parse_results("", DESKTOP_CHECKS)
        for c in DESKTOP_CHECKS:
            assert result["results"][c["id"]] is None

    def test_garbage_text_returns_none(self):
        text = "The desktop looks fine but I can't determine pass or fail."
        result = _parse_results(text, DESKTOP_CHECKS)
        for c in DESKTOP_CHECKS:
            assert result["results"][c["id"]] is None

    def test_raw_text_preserved_in_output(self):
        text = "1. Result: Pass. Evidence: OK."
        result = _parse_results(text, DESKTOP_CHECKS)
        assert result["raw"] == text

    def test_result_key_in_output(self):
        text = "Result: Pass"
        result = _parse_results(text, _make_checks(1))
        assert "results" in result
        assert "raw" in result

    def test_whitespace_only_text(self):
        result = _parse_results("   \n  \n  ", DESKTOP_CHECKS)
        for c in DESKTOP_CHECKS:
            assert result["results"][c["id"]] is None

    def test_result_without_pass_fail_keyword(self):
        """Result: line without Pass or Fail keyword → fallback sets found
        but doesn't assign a value, so the key is absent from results."""
        text = "Result: Unknown"
        checks = _make_checks(1)
        result = _parse_results(text, checks)
        assert "check-0" not in result["results"]

    def test_login_checks(self):
        text = "1. login prompt: Pass. Login screen visible."
        result = _parse_results(text, LOGIN_CHECKS)
        assert result["results"]["login-prompt"] is True

    def test_desktop_session_checks(self):
        text = (
            "1. desktop loaded: Pass. Panel visible.\n"
            "2. apps available: Fail. Blank areas detected.\n"
        )
        result = _parse_results(text, DESKTOP_SESSION_CHECKS)
        assert result["results"]["desktop-loaded"] is True
        assert result["results"]["apps-available"] is False

    def test_all_check_groups_combined(self):
        """Full desktop mode: DESKTOP_CHECKS + LOGIN_CHECKS + DESKTOP_SESSION_CHECKS."""
        all_checks = _checks(DESKTOP_CHECKS, LOGIN_CHECKS, DESKTOP_SESSION_CHECKS)
        lines = [f"{i+1}. Result: Pass." for i in range(len(all_checks))]
        text = "\n".join(lines)
        result = _parse_results(text, all_checks)
        for c in all_checks:
            assert result["results"][c["id"]] is True


# ── Test: encode_image ───────────────────────────────────────────────────────


class TestEncodeImage:
    """Tests for encode_image() — PNG re-encode to 1024px max dimension."""

    def test_small_image_not_resized(self):
        """Image under 1024px should keep original dimensions."""
        img = Image.new("RGB", (800, 600), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        path = buf.getvalue()

        # Write to a temp file for encode_image
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(path)
            tmp_path = f.name
        try:
            b64 = encode_image(tmp_path)
            decoded = base64.b64decode(b64)
            result = Image.open(io.BytesIO(decoded))
            assert result.size == (800, 600)
        finally:
            os.unlink(tmp_path)

    def test_large_image_resized_to_1024(self):
        """Image over 1024px should be resized so max dimension == 1024."""
        img = Image.new("RGB", (2048, 1024), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(buf.getvalue())
            tmp_path = f.name
        try:
            b64 = encode_image(tmp_path)
            decoded = base64.b64decode(b64)
            result = Image.open(io.BytesIO(decoded))
            assert max(result.size) == 1024
            # Width was the long side → 2048→1024, height 1024→512
            assert result.size == (1024, 512)
        finally:
            os.unlink(tmp_path)

    def test_square_large_image(self):
        """Square image > 1024 on both axes → both become 1024."""
        img = Image.new("RGB", (2000, 2000), color="green")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(buf.getvalue())
            tmp_path = f.name
        try:
            b64 = encode_image(tmp_path)
            decoded = base64.b64decode(b64)
            result = Image.open(io.BytesIO(decoded))
            assert result.size == (1024, 1024)
        finally:
            os.unlink(tmp_path)

    def test_output_is_valid_base64_png(self):
        """Returned base64 decodes to a valid PNG."""
        img = Image.new("RGB", (100, 100), color="yellow")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(buf.getvalue())
            tmp_path = f.name
        try:
            b64 = encode_image(tmp_path)
            decoded = base64.b64decode(b64)
            result = Image.open(io.BytesIO(decoded))
            assert result.format == "PNG"
            assert result.size == (100, 100)
        finally:
            os.unlink(tmp_path)

    def test_tall_image_resized(self):
        """Tall image (portrait) with height > 1024 gets resized."""
        img = Image.new("RGB", (512, 4096), color="purple")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(buf.getvalue())
            tmp_path = f.name
        try:
            b64 = encode_image(tmp_path)
            decoded = base64.b64decode(b64)
            result = Image.open(io.BytesIO(decoded))
            assert max(result.size) == 1024
            # Height was long side: 4096→1024, width 512→128
            assert result.size == (128, 1024)
        finally:
            os.unlink(tmp_path)

    def test_exactly_1024_not_resized(self):
        """Image with max dimension exactly 1024 is not resized."""
        img = Image.new("RGB", (1024, 768), color="orange")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(buf.getvalue())
            tmp_path = f.name
        try:
            b64 = encode_image(tmp_path)
            decoded = base64.b64decode(b64)
            result = Image.open(io.BytesIO(decoded))
            assert result.size == (1024, 768)
        finally:
            os.unlink(tmp_path)
