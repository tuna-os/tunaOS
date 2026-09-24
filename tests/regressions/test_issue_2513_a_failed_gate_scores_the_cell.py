"""tunaOS#2513: a cell whose Gate fails every night must not read untested.

hummingbird:gnome builds nightly and its boot Gate fails nightly (run
35938968035: 900s wait, no ``TUNAOS_DESKTOP_CONTRACT_OK``, because gdm and
gnome-shell never install -- see #2513). The failed Gate skips Promote.
build_stage_results() only fixed a cell on a conclusive Promote, so it stepped
past every one of those runs, and docs/matrix-provenance.json recorded the cell
as ``builds: untested`` and ``boots: untested`` with an empty run. The README
generator did the same and listed gnome as "never reached". A red Gate that
runs every night was reported as though nothing had ever looked at the cell.
It also meant an older green Promote, had one been in the window, would have
been read instead of the newer red Gate.

The rule now: a failed Gate scores the cell from that run (boots=fail), just as
a conclusive Promote does. A skipped Promote behind a passing or skipped Gate is
still not a verdict, and the walk continues -- that half is pinned by
tests/test_each_cell_is_scored_by_the_run_that_asserted_it.py.

Falsification: behavioural -- restore the Promote-only ``continue`` in
build_stage_results() and the Gate-failure fixtures below read untested
again, with no run; revert the matching branch in update-build-status.sh and the
bats case "a failed Gate that skipped Promote is failing, not unreached" in
tests/bats/test_build_status_classification.bats fails.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status_2513", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status_2513"] = gms
_spec.loader.exec_module(gms)

NEW, OLD = "35938968035", "35803090636"


def _jobs(*specs):
    out = []
    for flavor, promote, gate in specs:
        out.append({"name": f"x / {flavor} / Promote", "conclusion": promote})
        out.append({"name": f"x / {flavor} / Gate", "conclusion": gate})
    return {"jobs": out}


def _stage(views):
    runs = [
        {"databaseId": NEW, "conclusion": "failure",
         "createdAt": "2026-09-24T00:33:42Z"},
        {"databaseId": OLD, "conclusion": "failure",
         "createdAt": "2026-09-23T00:40:37Z"},
    ]

    def gh_json(*args):
        if args[:2] == ("run", "list"):
            return runs
        if args[:2] == ("run", "view"):
            return views[args[2]]
        raise AssertionError(args)

    with mock.patch.object(
        gms, "_matrix", return_value={"hummingbird": {"gnome", "cosmic"}}
    ), mock.patch.object(gms, "gh_json", gh_json):
        return gms.build_stage_results()


# The shape run 35938968035 actually had: gnome's Gate failed and its Promote
# was skipped; cosmic promoted with no Gate job at all.
NIGHTLY = _jobs(("gnome", "skipped", "failure"), ("cosmic", "success", "skipped"))


def test_a_failed_gate_fixes_the_cell_to_that_run():
    got = _stage({NEW: NIGHTLY, OLD: NIGHTLY})["hummingbird"]
    assert got["cell_run"]["gnome"][1] == NEW
    assert got["jobs"][("gnome", "Gate")] == "failure"
    # Promote was skipped: no builds verdict is invented for it.
    assert ("gnome", "Promote") not in got["jobs"]


def test_a_newer_failed_gate_beats_an_older_green_promote():
    got = _stage({
        NEW: NIGHTLY,
        OLD: _jobs(("gnome", "success", "success"),
                   ("cosmic", "success", "skipped")),
    })["hummingbird"]
    assert got["cell_run"]["gnome"][1] == NEW
    assert got["jobs"][("gnome", "Gate")] == "failure"
    assert ("gnome", "Promote") not in got["jobs"]


def test_the_provenance_names_the_run_and_scores_the_cell_red():
    stage = _stage({NEW: NIGHTLY, OLD: NIGHTLY})
    criteria = [
        {"id": "builds", "enforcement": "blocking"},
        {"id": "boots", "enforcement": "blocking"},
    ]
    with mock.patch.object(
        gms, "_matrix", return_value={"hummingbird": {"gnome", "cosmic"}}
    ), mock.patch.object(gms, "iso_matrix", return_value={}):
        _lines, _green, _total, prov = gms.composite_section(
            criteria, stage, {}, {}, {}, {}, {}, {}
        )
    boots = prov["hummingbird:gnome"]["boots"]
    assert boots["verdict"] == "fail"
    assert boots["run"].endswith(NEW)
    assert boots["date"] == "2026-09-24"
