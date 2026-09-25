"""tunaOS#2709: a refresh must not score a variant from a stale page of runs.

Two Matrix Status refreshes on 2026-09-25 each blanked one variant that had
not changed. The 08:10 refresh (run 36111443104) scored every skipjack cell
from run 35351369196 (2026-09-18), and the 08:45 refresh scored every
albacore cell from 35429236550 (2026-09-19). In both, the variant's nine newer
runs, including the green 2026-09-24 builds the other refresh read,
contributed nothing. The old run then fell outside the 2-day freshness SLA,
and 16 cells went from ✅ to ⬜ each time with nothing in the job log. The
composite count read 117 and 115 of 135 for fleets that were 133.

build_stage_results() now takes its run list from main_runs(), which checks
the list against the workflow's newest run on main (a separate API call),
fetches again when it is missing, and raises instead of scoring from a stale
page. A completed run whose `run view` has no jobs at all raises too, rather
than being stepped over.

Falsification: behavioural. With main_runs' membership check removed (return
the first list), test_a_stale_page_is_fetched_again and
test_a_page_that_stays_stale_fails_the_refresh fail (checked). With the
empty-jobs check removed, test_a_run_with_no_jobs_fails_the_refresh fails
(checked).
"""

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen-matrix-status.py"
_spec = importlib.util.spec_from_file_location("gen_matrix_status_2709", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status_2709"] = gms
_spec.loader.exec_module(gms)

NEW, OLD = "36064521567", "35351369196"
NEW_RUN = {"databaseId": NEW, "conclusion": "success", "createdAt": "2026-09-24T21:56:11Z"}
OLD_RUN = {"databaseId": OLD, "conclusion": "failure", "createdAt": "2026-09-18T13:38:12Z"}


def _jobs(run_label):
    return {
        "jobs": [
            {"name": "🍣-skipjack / generate_matrix", "conclusion": "success"},
            {"name": "🍣-skipjack / gnome / Gate", "conclusion": "success"},
            {"name": "🍣-skipjack / gnome / Promote", "conclusion": "success"},
        ]
    }


def _run(pages, views=None, newest=NEW):
    """pages: the successive answers `gh run list` gives."""
    views = views or {NEW: _jobs(NEW), OLD: _jobs(OLD)}
    pages = list(pages)
    calls = {"list": 0}

    def gh_json(*args):
        if args[0] == "api":
            return {"workflow_runs": [{"id": int(newest)}]}
        if args[:2] == ("run", "list"):
            calls["list"] += 1
            return pages.pop(0) if len(pages) > 1 else pages[0]
        if args[:2] == ("run", "view"):
            return views[args[2]]
        raise AssertionError(args)

    with (
        mock.patch.object(gms, "_matrix", return_value={"skipjack": {"gnome"}}),
        mock.patch.object(gms, "gh_json", gh_json),
        mock.patch.object(gms.time, "sleep"),
    ):
        return gms.build_stage_results()["skipjack"], calls["list"]


def test_a_current_page_is_used_as_is():
    got, lists = _run([[NEW_RUN, OLD_RUN]])
    assert got["cell_run"]["gnome"] == ("2026-09-24", NEW)
    assert lists == 1


def test_a_stale_page_is_fetched_again():
    # First answer: the page that starts ten runs back. Second: the real one.
    got, lists = _run([[OLD_RUN], [NEW_RUN, OLD_RUN]])
    assert got["cell_run"]["gnome"] == ("2026-09-24", NEW), (
        "the cell was scored from the stale page"
    )
    assert lists == 2


def test_a_page_that_stays_stale_fails_the_refresh():
    with pytest.raises(RuntimeError, match="newest run"):
        _run([[OLD_RUN]])


def test_a_run_with_no_jobs_fails_the_refresh():
    with pytest.raises(RuntimeError, match="no jobs"):
        _run([[NEW_RUN, OLD_RUN]], views={NEW: {"jobs": []}, OLD: _jobs(OLD)})


def test_a_workflow_with_no_runs_on_main_is_still_untested():
    def gh_json(*args):
        if args[0] == "api":
            return {"workflow_runs": []}
        if args[:2] == ("run", "list"):
            return []
        raise AssertionError(args)

    with (
        mock.patch.object(gms, "_matrix", return_value={"skipjack": {"gnome"}}),
        mock.patch.object(gms, "gh_json", gh_json),
    ):
        got = gms.build_stage_results()["skipjack"]
    assert got["cell_run"] == {}
