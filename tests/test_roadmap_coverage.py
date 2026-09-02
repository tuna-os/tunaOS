#!/usr/bin/env python3
"""Unit tests for scripts/gen-roadmap-coverage.py.

The coverage number in ROADMAP.md was miscounted six times in five days (#1295,
#1361) — not because repos changed, but because each count used a different
scope rule and a different idea of where ROADMAP.md had to live. The generator's
value is entirely in pinning those two rules, so these tests pin them too:

  * the denominator excludes archived and private repos, and *includes* forks;
  * a repo counts as planned via its **default branch**, whatever that is.

Everything runs off tests/fixtures/roadmap-coverage-repos.json, so no test here
touches the network.
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gen-roadmap-coverage.py"
FIXTURE = ROOT / "tests" / "fixtures" / "roadmap-coverage-repos.json"

_spec = importlib.util.spec_from_file_location("gen_roadmap_coverage", SCRIPT)
grc = importlib.util.module_from_spec(_spec)
sys.modules["gen_roadmap_coverage"] = grc
_spec.loader.exec_module(grc)

REPOS = json.loads(FIXTURE.read_text())


class TestScope(unittest.TestCase):
    """The denominator — the thing the six conflicting counts disagreed on."""

    def test_archived_and_private_are_out_of_scope(self):
        names = [r["name"] for r in grc.active(REPOS)]
        self.assertNotIn("letters", names, "archived repo counted in scope")
        self.assertNotIn("demo-repository", names, "private repo counted")

    def test_forks_are_in_scope(self):
        # Four of the org's active repos are forks it develops in; dropping
        # them would silently shrink the denominator.
        names = [r["name"] for r in grc.active(REPOS)]
        self.assertIn("bootc-installer", names)
        self.assertIn("mariner", names)

    def test_scope_is_sorted_case_insensitively(self):
        names = [r["name"] for r in grc.active(REPOS)]
        self.assertEqual(names, sorted(names, key=str.lower))


class TestDefaultBranch(unittest.TestCase):
    """The numerator — a ROADMAP on `dev` counts when `dev` is the default."""

    def test_roadmap_on_non_main_default_branch_counts_as_planned(self):
        block = grc.build(REPOS, today="2026-08-14")
        self.assertIn("bootc-installer", block.split("**Unplanned")[0])

    def test_non_main_default_branches_are_called_out(self):
        block = grc.build(REPOS, today="2026-08-14")
        self.assertIn("`bootc-installer` on `dev`", block)
        # mariner's default is `master` but it has no ROADMAP, so there is
        # nothing to explain — the note is about counted repos only.
        self.assertNotIn("`mariner` on `master`", block)

    def test_repo_with_no_default_branch_is_unplanned_not_an_error(self):
        empty = [r for r in REPOS if r["name"] == "empty-repo"]
        self.assertEqual(grc.default_branch(empty[0]), "")
        self.assertFalse(grc.has_roadmap(empty[0]))


class TestBlock(unittest.TestCase):
    def test_counts_and_percentage(self):
        block = grc.build(REPOS, today="2026-08-14")
        # Scope is 5 (7 fixtures less archived + private); 2 planned -> 40%.
        self.assertIn("**Per-repo ROADMAP coverage — 2 of 5 active repos (40%)**",
                      block)
        self.assertIn("measured 2026-08-14", block)

    def test_every_in_scope_repo_lands_in_exactly_one_roster(self):
        block = grc.build(REPOS, today="2026-08-14")
        planned, unplanned = block.split("**Unplanned")
        for repo in grc.active(REPOS):
            name = repo["name"]
            self.assertEqual(
                [name in planned, name in unplanned].count(True), 1,
                f"{name} is in neither roster or both",
            )

    def test_full_coverage_drops_the_unplanned_roster(self):
        done = [dict(r, hasRoadmap=True) for r in REPOS]
        block = grc.build(done, today="2026-08-14")
        self.assertIn("✅", block)
        self.assertNotIn("**Unplanned", block)

    def test_markers_wrap_the_block(self):
        block = grc.build(REPOS, today="2026-08-14")
        self.assertTrue(block.startswith(grc.BEGIN))
        self.assertTrue(block.endswith(grc.END))


class TestStructuralMasking(unittest.TestCase):
    """--check-structure must ignore live org state but catch hand-edits.

    Without this split, another repo gaining a ROADMAP.md would fail the drift
    check on every unrelated tunaOS pull request.
    """

    def test_another_repo_gaining_a_roadmap_is_not_drift(self):
        before = grc.build(REPOS, today="2026-08-14")
        after = grc.build([dict(r, hasRoadmap=True) if r["name"] == "remora"
                           else r for r in REPOS], today="2026-08-20")
        self.assertNotEqual(before, after)
        self.assertEqual(grc.structural(before), grc.structural(after))

    def test_hand_editing_the_block_is_drift(self):
        block = grc.build(REPOS, today="2026-08-14")
        tampered = block.replace(
            "Archived repos are out", "Archived repos are in")
        self.assertNotEqual(grc.structural(block), grc.structural(tampered))


class TestProbeFailure(unittest.TestCase):
    def test_api_failure_raises_instead_of_counting_as_unplanned(self):
        """A rate limit must not be reported as a planning gap."""
        def boom(_args):
            class P:
                returncode = 1
                stderr = "HTTP 403: API rate limit exceeded"
                stdout = ""
            return P()

        original, grc._gh = grc._gh, boom
        try:
            with self.assertRaises(grc.ProbeError):
                grc.has_roadmap({"name": "remora",
                                 "defaultBranchRef": {"name": "main"}})
        finally:
            grc._gh = original

    def test_404_is_a_real_absence(self):
        def missing(_args):
            class P:
                returncode = 1
                stderr = "gh: Not Found (HTTP 404)"
                stdout = ""
            return P()

        original, grc._gh = grc._gh, missing
        try:
            self.assertFalse(grc.has_roadmap(
                {"name": "remora", "defaultBranchRef": {"name": "main"}}))
        finally:
            grc._gh = original


class TestCommittedDoc(unittest.TestCase):
    def test_roadmap_has_the_generated_markers(self):
        text = (ROOT / "ROADMAP.md").read_text()
        self.assertIn(grc.BEGIN, text)
        self.assertIn(grc.END, text)
        self.assertLess(text.index(grc.BEGIN), text.index(grc.END))


if __name__ == "__main__":
    unittest.main()
