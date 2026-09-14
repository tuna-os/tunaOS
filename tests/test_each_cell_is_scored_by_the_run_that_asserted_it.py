#!/usr/bin/env python3
"""A targeted rebuild must not blank the cells it never scheduled.

build_stage_results() used to take ONE run view per variant — the newest
conclusive run — on the stated premise that "a build run asserts its whole
matrix at once, so the newest conclusive run IS the current state of every
cell it scheduled".

build-<variant>.yml accepts a flavor-filtered workflow_dispatch, so that
premise is false. On 2026-09-13 a one-flavor dispatch rebuilt bonito:gnome-t2
by itself (run 34768771243). It became the newest conclusive run, and the
README snapshot reported bonito **1/16** with fifteen cells "not reached" —
every one of which had promoted successfully hours earlier in runs 34750383558
and 34764063033, and was still the published tag. Reading "this run did not
schedule the cell" as "nothing is known about the cell" is exactly the
tunaOS#1730 conflation the rest of this table is built to avoid.

The rule now: each cell is scored by the newest conclusive run that actually
asserted it. A fresh failure still outranks an older success, because runs are
walked newest first and the first conclusive Promote wins.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status_percell", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status_percell"] = gms
_spec.loader.exec_module(gms)

NEW, OLD = "34768771243", "34750383558"


def _jobs(*specs):
    """(flavor, promote, gate) triples -> the job list `gh run view` returns."""
    out = []
    for flavor, promote, gate in specs:
        out.append({"name": f"x / {flavor} / Promote", "conclusion": promote})
        out.append({"name": f"x / {flavor} / Gate", "conclusion": gate})
    return {"jobs": out}


def _fake(runs, views):
    def gh_json(*args):
        if args[0] == "run" and args[1] == "list":
            return runs
        if args[0] == "run" and args[1] == "view":
            return views[args[2]]
        raise AssertionError(f"unexpected call {args}")
    return gh_json


class OneRunIsNotAVerdictOnEveryCell(unittest.TestCase):
    def setUp(self):
        # Two flavors configured; the newest run built only one of them.
        self.matrix = mock.patch.object(
            gms, "_matrix", return_value={"bonito": {"gnome", "gnome-t2"}}
        )
        self.matrix.start()
        self.addCleanup(self.matrix.stop)
        self.runs = [
            {"databaseId": NEW, "conclusion": "success",
             "createdAt": "2026-09-13T16:30:16Z"},
            {"databaseId": OLD, "conclusion": "success",
             "createdAt": "2026-09-13T11:00:00Z"},
        ]

    def _results(self, views):
        with mock.patch.object(gms, "gh_json", _fake(self.runs, views)):
            return gms.build_stage_results()["bonito"]

    def test_a_cell_the_newest_run_skipped_keeps_its_own_last_verdict(self):
        got = self._results({
            NEW: _jobs(("gnome-t2", "success", "success")),
            OLD: _jobs(("gnome", "success", "success"),
                       ("gnome-t2", "success", "success")),
        })
        self.assertEqual(got["jobs"][("gnome", "Promote")], "success")
        self.assertEqual(got["jobs"][("gnome-t2", "Promote")], "success")

    def test_the_cell_names_the_run_that_actually_scored_it(self):
        got = self._results({
            NEW: _jobs(("gnome-t2", "success", "success")),
            OLD: _jobs(("gnome", "success", "success"),
                       ("gnome-t2", "success", "success")),
        })
        self.assertEqual(got["cell_run"]["gnome-t2"][1], NEW)
        self.assertEqual(got["cell_run"]["gnome"][1], OLD)

    def test_a_fresh_failure_beats_an_older_success(self):
        # The whole point of walking newest first: nothing stale is laundered.
        got = self._results({
            NEW: _jobs(("gnome", "failure", "failure"),
                       ("gnome-t2", "success", "success")),
            OLD: _jobs(("gnome", "success", "success"),
                       ("gnome-t2", "success", "success")),
        })
        self.assertEqual(got["jobs"][("gnome", "Promote")], "failure")
        self.assertEqual(got["cell_run"]["gnome"][1], NEW)

    def test_a_cell_no_run_asserted_is_still_untested(self):
        # Absence of evidence stays absence of evidence (tunaOS#1730): reaching
        # further back must not invent a verdict that was never recorded.
        got = self._results({
            NEW: _jobs(("gnome-t2", "success", "success")),
            OLD: _jobs(("gnome-t2", "success", "success")),
        })
        self.assertNotIn(("gnome", "Promote"), got["jobs"])
        self.assertNotIn("gnome", got["cell_run"])

    def test_a_skipped_promote_does_not_fix_the_cell_to_the_newer_run(self):
        # A skipped Promote is what a stopped upstream stage leaves behind. It
        # is not a verdict, so the walk must keep going rather than freeze the
        # cell as untested at the newest run.
        got = self._results({
            NEW: _jobs(("gnome", "skipped", "skipped"),
                       ("gnome-t2", "success", "success")),
            OLD: _jobs(("gnome", "success", "success"),
                       ("gnome-t2", "success", "success")),
        })
        self.assertEqual(got["jobs"][("gnome", "Promote")], "success")
        self.assertEqual(got["cell_run"]["gnome"][1], OLD)

    def test_builds_and_boots_for_one_cell_come_from_one_image(self):
        # The Gate is read from the same run as the Promote. Mixing a Gate from
        # one build with a Promote from another would describe no real image.
        got = self._results({
            NEW: _jobs(("gnome", "skipped", "success"),
                       ("gnome-t2", "success", "success")),
            OLD: _jobs(("gnome", "success", "failure"),
                       ("gnome-t2", "success", "success")),
        })
        self.assertEqual(got["jobs"][("gnome", "Gate")], "failure")

    def test_the_walk_stops_once_every_cell_is_scored(self):
        # A build workflow that asserts its whole matrix must still cost one
        # run view, not ten.
        views = {NEW: _jobs(("gnome", "success", "success"),
                            ("gnome-t2", "success", "success")),
                 OLD: _jobs(("gnome", "success", "success"),
                            ("gnome-t2", "success", "success"))}
        seen = []

        def gh_json(*args):
            if args[0] == "run" and args[1] == "list":
                return self.runs
            seen.append(args[2])
            return views[args[2]]

        with mock.patch.object(gms, "gh_json", gh_json):
            gms.build_stage_results()
        self.assertEqual(seen, [NEW])


class TheGeneratorStillSaysWhyItWalks(unittest.TestCase):
    """Vacuity guard, tunaOS#1730 style: the tests above pass trivially if the
    walk is deleted and every cell simply reads from run zero. Pin the shape of
    the thing they are testing, not just its output."""

    def test_the_shell_generator_scores_cells_not_whole_runs(self):
        script = (Path(__file__).resolve().parents[1]
                  / ".github/scripts/update-build-status.sh").read_text()
        joined = " ".join(script.split())
        self.assertIn("promo_of[$flavor]", joined,
                      "update-build-status.sh no longer accumulates a per-cell "
                      "verdict; a filtered dispatch will blank whole rows again")
        self.assertIn("gate_of[$flavor]", joined)


if __name__ == "__main__":
    unittest.main()
