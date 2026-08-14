#!/usr/bin/env python3
"""Unit tests for scripts/desktop-verify.py

Tests _parse_results() parsing contracts, check matching, fallback handling,
and encode_image() image resizing / base64 encoding.

Run with: pytest tests/pytest/test_desktop_verify.py -v
"""

import base64
import importlib.util
import os
import sys
from io import BytesIO
import pytest
from PIL import Image

# Import scripts/desktop-verify.py dynamically
SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "desktop-verify.py"
)
spec = importlib.util.spec_from_file_location("desktop_verify", SCRIPT_PATH)
desktop_verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop_verify)

_parse_results = desktop_verify._parse_results
encode_image = desktop_verify.encode_image
DESKTOP_CHECKS = desktop_verify.DESKTOP_CHECKS


class TestParseResults:
    """Tests for _parse_results() parsing logic."""

    def test_all_pass_numbered_and_id_matching(self):
        vlm_output = (
            "1. Result: Pass. Evidence: Boot complete with graphical background\n"
            "2. Result: Pass. Evidence: Compositor is active, no text console\n"
            "3. Result: Pass. Evidence: No error dialogs present\n"
        )
        res = _parse_results(vlm_output, DESKTOP_CHECKS)
        assert res["results"]["boot-complete"] is True
        assert res["results"]["compositor-active"] is True
        assert res["results"]["no-crash"] is True

    def test_all_fail(self):
        vlm_output = (
            "1. Result: Fail. Evidence: System stuck on TTY prompt\n"
            "2. Result: Fail. Evidence: No compositor running\n"
            "3. Result: Fail. Evidence: Crash dialog visible\n"
        )
        res = _parse_results(vlm_output, DESKTOP_CHECKS)
        assert res["results"]["boot-complete"] is False
        assert res["results"]["compositor-active"] is False
        assert res["results"]["no-crash"] is False

    def test_mixed_verdicts_case_insensitive(self):
        vlm_output = (
            "1. boot complete: PASS - Desktop bar visible\n"
            "2. compositor active: FAIL - Blank screen\n"
            "3. no crash: PASS - Clean UI\n"
        )
        res = _parse_results(vlm_output, DESKTOP_CHECKS)
        assert res["results"]["boot-complete"] is True
        assert res["results"]["compositor-active"] is False
        assert res["results"]["no-crash"] is True

    def test_bare_result_fallback_quirk(self):
        """Pin the bare Result: fallback behavior (quality finding #1393).

        When lines don't match index/id phrases, the fallback loop checks
        line.strip().startswith('Result:'). It breaks on the first 'Result:' line,
        meaning an unnumbered multi-line block without ID matches causes every
        unmatched check to inherit the first 'Result:' line's verdict.
        """
        vlm_output = (
            "Result: Pass\n"
            "Result: Fail\n"
            "Result: Pass\n"
        )
        res = _parse_results(vlm_output, DESKTOP_CHECKS)
        # Because line 1 matches 'Result: Pass' without check id/index,
        # fallback assigns True for check 0, and because it breaks on first Result:
        # for subsequent checks without id matches, all checks inherit True.
        for c in DESKTOP_CHECKS:
            assert res["results"][c["id"]] is True

    def test_unmatched_lines_return_none(self):
        vlm_output = (
            "The image shows a blue sky.\n"
            "No desktop elements can be determined.\n"
        )
        res = _parse_results(vlm_output, DESKTOP_CHECKS)
        for c in DESKTOP_CHECKS:
            assert res["results"][c["id"]] is None


class TestEncodeImage:
    """Tests for encode_image() resizing and encoding logic."""

    def test_encode_small_image(self, tmp_path):
        img_path = str(tmp_path / "small.png")
        img = Image.new("RGB", (200, 150), color="blue")
        img.save(img_path)

        encoded = encode_image(img_path)
        decoded_bytes = base64.b64decode(encoded)
        decoded_img = Image.open(BytesIO(decoded_bytes))

        assert decoded_img.size == (200, 150)

    def test_encode_large_image_resizes_to_max_1024(self, tmp_path):
        img_path = str(tmp_path / "large.png")
        img = Image.new("RGB", (2048, 1536), color="red")
        img.save(img_path)

        encoded = encode_image(img_path)
        decoded_bytes = base64.b64decode(encoded)
        decoded_img = Image.open(BytesIO(decoded_bytes))

        # Max dimension should be 1024, maintaining 4:3 aspect ratio -> 1024 x 768
        assert max(decoded_img.size) == 1024
        assert decoded_img.size == (1024, 768)
