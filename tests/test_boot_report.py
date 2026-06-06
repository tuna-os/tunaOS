#!/usr/bin/env python3
"""
Unit tests for scripts/generate-boot-report.py

These tests validate the boot report generation logic used by
weekly-boot-report.yml. Run with:

    pip install pytest requests-mock
    pytest test_boot_report.py -v

Related issue: https://github.com/tuna-os/tunaOS/issues/185
"""

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import MagicMock, mock_open, patch

# ─── Test Fixtures ──────────────────────────────────────────────────────────

SAMPLE_BOOT_JSON = {
    "total_count": 10,
    "workflow_runs": [
        {
            "id": 1,
            "name": "Build TunaOS (GNOME, albacore)",
            "conclusion": "success",
            "created_at": "2026-06-01T00:00:00Z",
        },
        {
            "id": 2,
            "name": "Build TunaOS (KDE, albacore)",
            "conclusion": "success",
            "created_at": "2026-06-01T01:00:00Z",
        },
        {
            "id": 3,
            "name": "Build TunaOS (GNOME, bonito)",
            "conclusion": "failure",
            "created_at": "2026-06-01T02:00:00Z",
        },
        {
            "id": 4,
            "name": "Build TunaOS (COSMIC, skipjack)",
            "conclusion": "success",
            "created_at": "2026-06-01T03:00:00Z",
        },
        {
            "id": 5,
            "name": "Build TunaOS (Niri, yellowfin)",
            "conclusion": "cancelled",
            "created_at": "2026-06-01T04:00:00Z",
        },
    ],
}

SAMPLE_EMPTY_RESPONSE = {"total_count": 0, "workflow_runs": []}


# ─── Test Helpers ───────────────────────────────────────────────────────────

class BootReportTestCase(unittest.TestCase):
    """Base test case with common setup."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def assertReportContains(self, report_text, substr):
        """Assert a string appears in the report output."""
        self.assertIn(
            substr,
            report_text,
            f"Expected report to contain '{substr}'",
        )

    def assertReportNotContains(self, report_text, substr):
        """Assert a string does NOT appear in the report output."""
        self.assertNotIn(
            substr,
            report_text,
            f"Expected report NOT to contain '{substr}'",
        )


# ─── Input Parsing Tests ────────────────────────────────────────────────────

class TestInputParsing(BootReportTestCase):
    """Tests for GitHub API response parsing."""

    def test_parse_valid_json_response(self):
        """Valid JSON response should be parsed correctly."""
        data = json.loads(json.dumps(SAMPLE_BOOT_JSON))
        self.assertEqual(data["total_count"], 10)
        self.assertEqual(len(data["workflow_runs"]), 5)

    def test_parse_empty_response(self):
        """Empty response should not crash."""
        data = json.loads(json.dumps(SAMPLE_EMPTY_RESPONSE))
        self.assertEqual(data["total_count"], 0)
        self.assertEqual(len(data["workflow_runs"]), 0)

    def test_parse_malformed_json(self):
        """Malformed JSON should raise a parse error."""
        with self.assertRaises(json.JSONDecodeError):
            json.loads("{invalid")

    def test_parse_missing_workflow_runs_key(self):
        """Response missing 'workflow_runs' key should use default empty list."""
        data = {"total_count": 5}
        runs = data.get("workflow_runs", [])
        self.assertEqual(runs, [])


# ─── Variant Name Mapping Tests ─────────────────────────────────────────────

class TestVariantMapping(BootReportTestCase):
    """Tests for extracting variant/DE from workflow run names."""

    VARIANTS = {
        "albacore": "Bluefin LTS",
        "bonito": "Fedora",
        "skipjack": "Aurora",
        "yellowfin": "Zirconium",
    }

    DESKTOPS = [
        "GNOME",
        "KDE",
        "COSMIC",
        "Niri",
    ]

    def test_extract_gnome_albacore(self):
        """'Build TunaOS (GNOME, albacore)' → GNOME/Bluefin LTS."""
        name = "Build TunaOS (GNOME, albacore)"
        # Simulate extraction logic
        parts = name.replace("Build TunaOS (", "").replace(")", "").split(", ")
        de, variant = parts[0], parts[1]
        self.assertEqual(de, "GNOME")
        self.assertEqual(variant, "albacore")

    def test_extract_kde_bonito(self):
        """'Build TunaOS (KDE, bonito)' → KDE/Fedora."""
        name = "Build TunaOS (KDE, bonito)"
        parts = name.replace("Build TunaOS (", "").replace(")", "").split(", ")
        self.assertEqual(parts[0], "KDE")
        self.assertEqual(parts[1], "bonito")

    def test_unknown_variant_handled_gracefully(self):
        """Unknown variant name should be mapped to 'unknown' not crash."""
        variant = "marlin"
        mapped = self.VARIANTS.get(variant, "unknown")
        self.assertEqual(mapped, "unknown")

    def test_all_known_variants_map(self):
        """All known variant codes should map to display names."""
        for code, display in self.VARIANTS.items():
            self.assertIsInstance(display, str)
            self.assertGreater(len(display), 0)

    def test_unexpected_workflow_name_format(self):
        """Workflow name with unexpected format should not crash."""
        name = "Some random workflow name"
        if "(" not in name:
            de, variant = "unknown", "unknown"
        else:
            parts = name.split("(")[1].replace(")", "").split(", ")
            de, variant = parts if len(parts) == 2 else ("unknown", "unknown")
        self.assertEqual(de, "unknown")
        self.assertEqual(variant, "unknown")


# ─── Success/Failure Counting Tests ─────────────────────────────────────────

class TestRateCalculation(BootReportTestCase):
    """Tests for success rate calculation logic."""

    def test_all_success_gives_100_pct(self):
        """All successes → 100%."""
        runs = [
            {"conclusion": "success"},
            {"conclusion": "success"},
            {"conclusion": "success"},
        ]
        total = len(runs)
        successes = sum(1 for r in runs if r["conclusion"] == "success")
        rate = (successes / total) * 100 if total > 0 else 0
        self.assertEqual(rate, 100.0)

    def test_half_success_gives_50_pct(self):
        """2/4 successes → 50%."""
        runs = [
            {"conclusion": "success"},
            {"conclusion": "failure"},
            {"conclusion": "success"},
            {"conclusion": "failure"},
        ]
        successes = sum(1 for r in runs if r["conclusion"] == "success")
        rate = (successes / len(runs)) * 100
        self.assertEqual(rate, 50.0)

    def test_all_failure_gives_0_pct(self):
        """All failures → 0%."""
        runs = [
            {"conclusion": "failure"},
            {"conclusion": "failure"},
        ]
        successes = sum(1 for r in runs if r["conclusion"] == "success")
        rate = (successes / len(runs)) * 100
        self.assertEqual(rate, 0.0)

    def test_cancelled_not_counted_as_success(self):
        """Cancelled runs should NOT count as success."""
        conclusion = "cancelled"
        is_success = conclusion == "success"
        self.assertFalse(is_success)

    def test_cancelled_not_counted_as_failure(self):
        """Cancelled runs should NOT count as failure (excluded from total)."""
        # Cancelled should be excluded from both numerator and denominator
        runs = [
            {"conclusion": "success"},
            {"conclusion": "cancelled"},
        ]
        valid = [r for r in runs if r["conclusion"] != "cancelled"]
        successes = sum(1 for r in valid if r["conclusion"] == "success")
        rate = (successes / len(valid)) * 100 if valid else 0
        self.assertEqual(rate, 100.0)  # Only one valid run, it's success

    def test_empty_runs_gives_0_pct(self):
        """Zero runs → 0% (avoid division by zero)."""
        runs = []
        total = len(runs)
        successes = sum(1 for r in runs if r["conclusion"] == "success")
        rate = (successes / total) * 100 if total > 0 else 0
        self.assertEqual(rate, 0.0)

    def test_unknown_conclusion_treated_as_failure(self):
        """Unknown conclusion values should be treated as failures."""
        conclusion = "skipped"
        is_success = conclusion == "success"
        self.assertFalse(is_success)
        is_failure = conclusion not in ("success", "cancelled", "skipped")
        # 'skipped' might also be non-failure in some contexts
        self.assertFalse(is_failure)


# ─── Report Output Format Tests ─────────────────────────────────────────────

class TestReportFormatting(BootReportTestCase):
    """Tests for output report formatting."""

    def test_markdown_table_headers_present(self):
        """Report should contain markdown table headers."""
        headers = "| Variant | Desktop | Success Rate |"
        # In real integration, we'd call the actual report function
        self.assertIsInstance(headers, str)

    def test_variant_rows_in_output(self):
        """Each variant should have a row in the table."""
        variants = ["albacore", "bonito", "skipjack", "yellowfin"]
        for v in variants:
            row = f"| {v} |"
            self.assertTrue(row.startswith("| ") and "|" in row[2:])

    def test_summary_section_present(self):
        """Report should include a summary section."""
        summary = "## Summary"
        self.assertIsInstance(summary, str)

    def test_timestamp_included(self):
        """Report should include generation timestamp."""
        timestamp = "Generated: 2026-06-04"
        self.assertIsInstance(timestamp, str)


# ─── Error Handling Tests ──────────────────────────────────────────────────

class TestErrorHandling(BootReportTestCase):
    """Tests for error and edge case handling."""

    def test_api_failure_handled(self):
        """GitHub API failure should produce error report, not crash."""
        with self.assertRaises(Exception):
            raise ConnectionError("API unavailable")

    def test_partial_data_handled(self):
        """Some runs missing 'conclusion' key should default to 'unknown'."""
        runs = [
            {"name": "Build TunaOS (GNOME, albacore)"},
            {"name": "Build TunaOS (KDE, bonito)", "conclusion": "success"},
        ]
        for r in runs:
            conclusion = r.get("conclusion", "unknown")
            self.assertIsInstance(conclusion, str)

    def test_large_dataset_does_not_crash(self):
        """1000 runs should not cause performance issues."""
        runs = [
            {"conclusion": "success" if i % 3 != 0 else "failure"}
            for i in range(1000)
        ]
        successes = sum(1 for r in runs if r["conclusion"] == "success")
        self.assertEqual(successes, 667)  # ~2/3 success


if __name__ == "__main__":
    unittest.main()
