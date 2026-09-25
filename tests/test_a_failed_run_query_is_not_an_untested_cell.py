#!/usr/bin/env python3
"""A failed `gh` query must not render a built variant as never tested.

The 2026-09-24 Matrix Status refresh (run 35990117734, commit d25d153a) moved
all 16 bonito cells from builds ✅ to builds ⬜ with an empty run and date, and
the composite count from 128 to 112 of 135. Nothing about bonito had changed:
run 35881676275 on 2026-09-23 promoted all 16 cells, and re-deriving the table
from that run with the same code scores 16/16 again. The only way
build_stage_results() emits an empty run for every cell of a variant whose
workflow has conclusive runs is `gh_json(...) or []` / `or {}` turning a
thrice-failed `gh` call into "no runs" — and the job log recorded nothing,
because gh_json swallowed gh's stderr.

The module docstring already promised the opposite ("an API failure raises
rather than silently degrading a cell to unknown"). These tests hold it for
the build/boot axes.

Falsification: behavioural — restore `or []` on the `run list` call or
`or {}` on the `run view` call in build_stage_results() and the two
`assertRaises` tests fail, because the unfixed code returns empty jobs instead.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
import unittest.mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status_failedquery", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status_failedquery"] = gms
_spec.loader.exec_module(gms)

RUN = "35881676275"
RUNS = [{"databaseId": RUN, "conclusion": "success",
         "createdAt": "2026-09-23T15:27:21Z"}]
JOBS = {"jobs": [
    {"name": "🎣-bonito / gnome / Promote", "conclusion": "success"},
    {"name": "🎣-bonito / gnome / Gate", "conclusion": "success"},
    # Attest SBOM failed on every cell of that run (Rekor 502) and must not
    # colour the builds axis either way: only Promote and Gate are read.
    {"name": "🎣-bonito / gnome / Attest SBOM", "conclusion": "failure"},
]}


def _gh(list_result, view_result):
    def fake(*args):
        if args[0] == "api":  # main_runs' newest-run cross-check
            runs = list_result or []
            return {"workflow_runs": [{"id": runs[0]["databaseId"]}] if runs else []}
        if args[:2] == ("run", "list"):
            return list_result
        if args[:2] == ("run", "view"):
            return view_result
        raise AssertionError(f"unexpected call {args}")
    return fake


class AFailedQueryIsNotAbsenceOfRuns(unittest.TestCase):
    def setUp(self):
        patcher = unittest.mock.patch.object(
            gms, "_matrix", return_value={"bonito": {"gnome"}}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _results(self, list_result, view_result):
        with unittest.mock.patch.object(gms, "gh_json", _gh(list_result, view_result)):
            return gms.build_stage_results()["bonito"]

    def test_a_failed_run_list_raises_instead_of_scoring_untested(self):
        with self.assertRaises(RuntimeError):
            self._results(None, JOBS)

    def test_a_failed_run_view_raises_instead_of_scoring_untested(self):
        with self.assertRaises(RuntimeError):
            self._results(RUNS, None)

    def test_a_variant_with_genuinely_no_runs_is_still_untested(self):
        # `gh run list` prints [] for a workflow with no runs; that IS
        # absence of evidence and must stay ⬜, not raise.
        got = self._results([], JOBS)
        self.assertEqual(got["jobs"], {})
        self.assertEqual(got["cell_run"], {})

    def test_the_run_that_promoted_the_cell_is_named(self):
        got = self._results(RUNS, JOBS)
        self.assertEqual(got["jobs"][("gnome", "Promote")], "success")
        self.assertEqual(got["cell_run"]["gnome"], ("2026-09-23", RUN))


class GhJsonSaysWhatFailed(unittest.TestCase):
    def test_the_final_failure_is_logged_with_the_command(self):
        err = gms.subprocess.CalledProcessError(
            1, "gh", stderr="HTTP 502: Bad Gateway"
        )
        with unittest.mock.patch.object(gms.subprocess, "run", side_effect=err), \
                unittest.mock.patch.object(gms.time, "sleep"), \
                unittest.mock.patch.object(gms.sys, "stderr") as stderr:
            self.assertIsNone(gms.gh_json("run", "list"))
        written = "".join(c.args[0] for c in stderr.write.call_args_list)
        self.assertIn("gh run list", written)
        self.assertIn("HTTP 502", written)


if __name__ == "__main__":
    unittest.main()
