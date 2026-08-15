#!/usr/bin/env python3
"""Unit tests for the fetch and classification layer of gen-matrix-status.py.

tests/test_matrix_status.py covers the drift gate — what `--check-structure`
ignores and what it catches. It does not touch the half of the script that
decides *what the cells say in the first place*: the `gh` subprocess wrapper,
the run-list walk, and the pass/fail/never-tested classification. Those are the
paths tunaOS#1721 flags as uncovered, and they are the ones that can put a
wrong answer on an org-facing status page rather than merely failing a PR.

Kept in a separate file rather than appended to test_matrix_status.py: that
file is organised around the drift-gate contract and is currently touched by
other open PRs, so a new file is both clearer and less likely to conflict.

Nothing here talks to the network. `gh_json` is the only door to the outside,
so mocking `subprocess.run` at that door covers every fetch path.
"""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status"] = gms
_spec.loader.exec_module(gms)


def _completed(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=0, stdout=stdout)


class GhJsonIsTheOnlyDoorOutside(unittest.TestCase):
    """The subprocess wrapper: parsing, retries, and what a failure returns."""

    def test_parses_json_from_stdout(self):
        with mock.patch.object(gms.subprocess, "run",
                               return_value=_completed('{"a": 1}')) as run:
            self.assertEqual(gms.gh_json("run", "list"), {"a": 1})
        # The command is passed through verbatim, prefixed with `gh`.
        self.assertEqual(run.call_args.args[0], ["gh", "run", "list"])

    def test_empty_output_is_none_not_a_crash(self):
        # `gh` prints nothing for some empty queries; that is not a parse error.
        with mock.patch.object(gms.subprocess, "run", return_value=_completed("   ")):
            self.assertIsNone(gms.gh_json("run", "list"))

    def test_retries_three_times_before_giving_up(self):
        err = subprocess.CalledProcessError(1, "gh")
        with mock.patch.object(gms.subprocess, "run", side_effect=err) as run, \
                mock.patch.object(gms.time, "sleep") as sleep:
            self.assertIsNone(gms.gh_json("run", "list"))
        self.assertEqual(run.call_count, 3)
        # Sleeps between attempts, not after the last one.
        self.assertEqual(sleep.call_count, 2)

    def test_a_transient_failure_recovers_on_a_later_attempt(self):
        # The retry has to actually be useful, not just burn attempts.
        err = subprocess.CalledProcessError(1, "gh")
        with mock.patch.object(gms.subprocess, "run",
                               side_effect=[err, _completed('{"ok": true}')]), \
                mock.patch.object(gms.time, "sleep"):
            self.assertEqual(gms.gh_json("run", "list"), {"ok": True})

    def test_malformed_json_is_retried_then_gives_up(self):
        with mock.patch.object(gms.subprocess, "run",
                               return_value=_completed("not json")) as run, \
                mock.patch.object(gms.time, "sleep"):
            self.assertIsNone(gms.gh_json("run", "list"))
        self.assertEqual(run.call_count, 3)


class CellClassification(unittest.TestCase):
    """A cell may only read pass or fail if a run actually asserted it."""

    def test_success_is_a_pass(self):
        results = {"k": ("success", "2026-08-06", "1")}
        self.assertEqual(gms.cell(results, "k", True), gms.PASS)

    def test_failure_is_a_fail(self):
        results = {"k": ("failure", "2026-08-06", "1")}
        self.assertEqual(gms.cell(results, "k", True), gms.FAIL)

    def test_scheduled_but_never_run_is_untested_not_passing(self):
        # The whole point of the document: absence of a result is not success.
        self.assertEqual(gms.cell({}, "k", True), gms.UNTESTED)

    def test_not_scheduled_and_never_run_is_not_applicable(self):
        self.assertEqual(gms.cell({}, "k", False), gms.NA)

    def test_a_real_result_outranks_not_built(self):
        # The sailfin case in cell()'s docstring: build_iso is false everywhere,
        # yet LUKS E2E covers it. Keying off the matrix alone dropped four
        # tested cells, so a result must win over "not built".
        results = {"k": ("success", "2026-08-06", "1")}
        self.assertEqual(gms.cell(results, "k", False), gms.PASS)


class RunWalkPicksTheNewestAuthoritativeResult(unittest.TestCase):
    """latest_results walks newest-first and keeps the first hit per job."""

    def _fetch(self, runs, jobs_by_run, name_re=r"^cell "):
        def fake(*args):
            if args[0] == "run" and args[1] == "list":
                return runs
            if args[0] == "run" and args[1] == "view":
                return {"jobs": jobs_by_run.get(args[2], [])}
            return None

        with mock.patch.object(gms, "gh_json", side_effect=fake):
            return gms.latest_results("wf.yml", name_re)

    def test_a_rerun_supersedes_the_older_sweep(self):
        runs = [
            {"databaseId": 2, "createdAt": "2026-08-06T00:00:00Z", "status": "completed"},
            {"databaseId": 1, "createdAt": "2026-08-05T00:00:00Z", "status": "completed"},
        ]
        jobs = {
            "2": [{"name": "cell a", "conclusion": "success"}],
            "1": [{"name": "cell a", "conclusion": "failure"}],
        }
        got = self._fetch(runs, jobs)
        self.assertEqual(got["cell a"], ("success", "2026-08-06", "2"))

    def test_in_flight_runs_are_skipped_entirely(self):
        runs = [
            {"databaseId": 2, "createdAt": "2026-08-06T00:00:00Z", "status": "in_progress"},
            {"databaseId": 1, "createdAt": "2026-08-05T00:00:00Z", "status": "completed"},
        ]
        jobs = {
            "2": [{"name": "cell a", "conclusion": "success"}],
            "1": [{"name": "cell a", "conclusion": "failure"}],
        }
        # The newer run is not completed, so the older result stands.
        self.assertEqual(self._fetch(runs, jobs)["cell a"][0], "failure")

    def test_jobs_not_matching_the_pattern_are_ignored(self):
        runs = [{"databaseId": 1, "createdAt": "2026-08-06T00:00:00Z", "status": "completed"}]
        jobs = {"1": [
            {"name": "cell a", "conclusion": "success"},
            {"name": "setup runner", "conclusion": "success"},
        ]}
        self.assertEqual(set(self._fetch(runs, jobs)), {"cell a"})

    def test_cancelled_and_skipped_conclusions_are_not_results(self):
        # Only success/failure assert anything. A cancelled job must leave the
        # cell never-tested rather than inventing an answer.
        runs = [{"databaseId": 1, "createdAt": "2026-08-06T00:00:00Z", "status": "completed"}]
        jobs = {"1": [
            {"name": "cell a", "conclusion": "cancelled"},
            {"name": "cell b", "conclusion": "skipped"},
            {"name": "cell c", "conclusion": None},
        ]}
        self.assertEqual(self._fetch(runs, jobs), {})


class ApiOutageCurrentlyDegradesSilently(unittest.TestCase):
    """Characterises a gap between the module docstring and the behaviour.

    gen-matrix-status.py's header says:

        "an API failure raises rather than silently degrading a cell to
         unknown — a status page that quietly downgrades itself is worse
         than no status page."

    It does not raise. `gh_json` returns None after three attempts, and
    `latest_results` does `gh_json(...) or []`, so a total API outage yields
    zero results and every scheduled cell renders UNTESTED — the page quietly
    downgrades itself, which is the outcome the docstring calls worse than
    nothing. There is no signal: no raise, no non-zero exit, only ⬜.

    This is pinned rather than fixed. Making the script fail closed changes the
    behaviour of a CI gate that runs on a schedule and on pull requests, which
    is a maintainer's call, not a coverage task's (tunaOS#1721). The test is
    written so that a fix is a deliberate, visible edit here rather than a
    silent behaviour change.
    """

    def test_total_api_failure_yields_no_results_and_does_not_raise(self):
        with mock.patch.object(gms, "gh_json", return_value=None):
            self.assertEqual(gms.latest_results("wf.yml", r"^cell "), {})

    def test_and_those_empty_results_render_every_cell_as_never_tested(self):
        with mock.patch.object(gms, "gh_json", return_value=None):
            results = gms.latest_results("wf.yml", r"^cell ")
        self.assertEqual(gms.cell(results, "cell a", True), gms.UNTESTED)


if __name__ == "__main__":
    unittest.main()
