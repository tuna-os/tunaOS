#!/usr/bin/env python3
"""Regression tests for the generated organization release inventory (#2828)."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gen-org-release-inventory.py"
FIXTURE = ROOT / "tests" / "fixtures" / "org-release-inventory-repos.json"

_spec = importlib.util.spec_from_file_location("gen_org_release_inventory", SCRIPT)
gri = importlib.util.module_from_spec(_spec)
sys.modules["gen_org_release_inventory"] = gri
_spec.loader.exec_module(gri)
REPOS = json.loads(FIXTURE.read_text())


class TestScope(unittest.TestCase):
    def test_only_active_public_repositories_are_counted(self):
        names = [repo["name"] for repo in gri.active(REPOS)]
        self.assertEqual(names, ["alpha", "bravo", "charlie", "delta"])


class TestVersionPattern(unittest.TestCase):
    def test_semver_including_release_candidates(self):
        self.assertEqual(gri.version_pattern("v1.2.3"), "SemVer")
        self.assertEqual(gri.version_pattern("v0.2.0-rc.1"), "SemVer")

    def test_prefixed_image_dates_are_date_based(self):
        self.assertEqual(gri.version_pattern("gnome-20261003"), "date-based")
        self.assertEqual(gri.version_pattern("v2026.09.26-253d6938"), "date-based")

    def test_absent_and_unrecognized_refs_are_not_guessed(self):
        self.assertEqual(gri.version_pattern(None), "none")
        self.assertEqual(gri.version_pattern("preview"), "other")


class TestReleaseSelection(unittest.TestCase):
    def test_draft_releases_are_not_reported(self):
        values = gri.releases({
            "releases": [
                {"tag_name": "v2.0.0", "draft": True},
                {"tag_name": "v1.0.0", "draft": False},
            ]
        })
        self.assertEqual([release["tag_name"] for release in values], ["v1.0.0"])


class TestRenderedInventory(unittest.TestCase):
    def setUp(self):
        self.doc = gri.render(REPOS, measured="2026-10-03")

    def test_summary_is_derived_from_fixture(self):
        self.assertIn("Active public repositories: **4**", self.doc)
        self.assertIn("published GitHub Release: **2**", self.doc)
        self.assertIn("no Git tag or GitHub Release: **1**", self.doc)
        self.assertIn("**2 SemVer**, **1 date-based**", self.doc)

    def test_release_evidence_links_to_the_release(self):
        self.assertIn(
            "[`v1.2.3`](https://github.com/tuna-os/alpha/releases/tag/v1.2.3)",
            self.doc,
        )
        self.assertIn("(pre-release)", self.doc)

    def test_asset_markers_are_descriptive_not_a_validation_claim(self):
        self.assertIn("4 (checksum, SBOM, signature/provenance)", self.doc)
        self.assertIn("filename and is not a cryptographic validation", self.doc)
        self.assertIn("1 (installer/package)", self.doc)

    def test_unversioned_repository_remains_visible(self):
        self.assertRegex(
            self.doc,
            r"\| \[charlie\]\([^)]*\) \| — \| — \| none \| 0 \|",
        )


class TestProbeFailure(unittest.TestCase):
    def test_api_failure_raises_instead_of_reporting_no_release(self):
        def failed(_args):
            class Result:
                returncode = 1
                stdout = ""
                stderr = "HTTP 403: rate limit exceeded"

            return Result()

        original, gri._gh = gri._gh, failed
        try:
            with self.assertRaises(gri.ProbeError):
                gri.tags({"name": "alpha"})
        finally:
            gri._gh = original


if __name__ == "__main__":
    unittest.main()
