#!/usr/bin/env python3
"""A run whose jobs the API will not list is skipped, not fatal.

On 2026-10-16 the jobs endpoint answered HTTP 502 on every attempt for runs
31224494825, 38713238238 and 38592759334 at `gh run view`'s fixed page size
of 100, while per_page=50 on the same runs answered in seconds. 38592759334
was a conclusive build-bonito.yml run, so build_stage_results() raised on it
and the regenerate check failed on every pull request.

Now run_jobs() retries the jobs endpoint in smaller pages, and a run that
still cannot be read is skipped with a warning: its cells fall to the next run
that asserted them. If a run was skipped and any configured cell is still
unscored when the walk ends, the skipped run may have held that cell's
verdict, so the refresh still raises (see also
test_a_failed_run_query_is_not_an_untested_cell.py).

Falsification: behavioural. Make run_jobs() return None without the
small-page fallback and test_the_small_page_fallback_reads_the_run fails;
put gh_json_required back on the build walk's job query and
test_an_unreadable_newer_run_falls_to_the_older_one raises.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status_unreadable", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status_unreadable"] = gms
_spec.loader.exec_module(gms)

NEW, OLD = "38592759334", "38500000000"
RUNS = [
    {"databaseId": NEW, "conclusion": "success", "createdAt": "2026-10-14T15:49:44Z"},
    {"databaseId": OLD, "conclusion": "success", "createdAt": "2026-10-13T15:00:00Z"},
]


def _jobs(promote, flavor="gnome"):
    return [
        {"name": f"🎣-bonito / {flavor} / Promote", "conclusion": promote},
        {"name": f"🎣-bonito / {flavor} / Gate", "conclusion": "success"},
    ]


def _fake(views, pages):
    """views/pages: run id -> `gh run view` result / slurped API pages (None = 502)."""
    calls = []

    def gh_json(*args):
        calls.append(args)
        if args[:2] == ("api", "--paginate"):
            run_id = args[3].split("/runs/")[1].split("/")[0]
            return pages.get(run_id)
        if args[0] == "api":  # main_runs' newest-run cross-check
            return {"workflow_runs": [{"id": RUNS[0]["databaseId"]}]}
        if args[:2] == ("run", "list"):
            return RUNS
        if args[:2] == ("run", "view"):
            return views.get(args[2])
        raise AssertionError(args)

    return gh_json, calls


class AnUnreadableRunIsSkipped(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(gms, "_matrix", return_value={"bonito": {"gnome"}})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _results(self, views, pages):
        fake, calls = _fake(views, pages)
        with mock.patch.object(gms, "gh_json", fake), \
                mock.patch.object(gms.sys, "stderr") as stderr:
            got = gms.build_stage_results()["bonito"]
        written = "".join(c.args[0] for c in stderr.write.call_args_list)
        return got, calls, written

    def test_the_small_page_fallback_reads_the_run(self):
        got, calls, _ = self._results(
            views={NEW: None},
            pages={NEW: [{"jobs": _jobs("failure")[:1]}, {"jobs": _jobs("failure")[1:]}]},
        )
        self.assertEqual(got["jobs"][("gnome", "Promote")], "failure")
        self.assertEqual(got["cell_run"]["gnome"], ("2026-10-14", NEW))
        fallback = [c for c in calls if c[:2] == ("api", "--paginate")]
        self.assertEqual(len(fallback), 1)
        self.assertIn(f"per_page={gms.JOBS_PAGE}", fallback[0][-1])

    def test_an_unreadable_newer_run_falls_to_the_older_one(self):
        got, _, written = self._results(
            views={NEW: None, OLD: {"jobs": _jobs("success")}},
            pages={NEW: None},
        )
        self.assertEqual(got["jobs"][("gnome", "Promote")], "success")
        self.assertEqual(got["cell_run"]["gnome"], ("2026-10-13", OLD))
        self.assertIn(NEW, written)
        self.assertIn("skipping", written)

    def test_no_readable_run_still_raises(self):
        with self.assertRaises(RuntimeError):
            self._results(views={}, pages={})

    def test_a_cell_only_the_skipped_run_could_score_raises(self):
        # Full build unreadable, the older run a GNOME-only dispatch: KDE has
        # no readable verdict, and scoring it untested would erase evidence.
        with mock.patch.object(gms, "_matrix",
                               return_value={"bonito": {"gnome", "kde"}}):
            with self.assertRaises(RuntimeError) as raised:
                self._results(
                    views={NEW: None, OLD: {"jobs": _jobs("success")}},
                    pages={NEW: None},
                )
        self.assertIn("kde", str(raised.exception))

    def test_every_cell_scored_from_older_runs_is_not_fatal(self):
        with mock.patch.object(gms, "_matrix",
                               return_value={"bonito": {"gnome", "kde"}}):
            got, _, _ = self._results(
                views={NEW: None,
                       OLD: {"jobs": _jobs("success") + _jobs("failure", "kde")}},
                pages={NEW: None},
            )
        self.assertEqual(got["jobs"][("kde", "Promote")], "failure")
        self.assertEqual(got["cell_run"]["kde"], ("2026-10-13", OLD))


class LatestResultsReadsThroughTheFallback(unittest.TestCase):
    def test_a_run_view_502_is_read_in_smaller_pages(self):
        runs = [{"databaseId": NEW, "createdAt": "2026-10-15T09:28:52Z",
                 "status": "completed"}]
        pages = [{"jobs": [{"name": "LUKS albacore:gnome", "conclusion": "success"}]}]

        def fake(*args):
            if args[:2] == ("run", "list"):
                return runs
            if args[:2] == ("run", "view"):
                return None
            if args[:2] == ("api", "--paginate"):
                return pages
            raise AssertionError(args)

        with mock.patch.object(gms, "gh_json", fake):
            got = gms.latest_results("luks-e2e.yml", r"^LUKS ")
        self.assertEqual(got, {"LUKS albacore:gnome": ("success", "2026-10-15", NEW)})


if __name__ == "__main__":
    unittest.main()
