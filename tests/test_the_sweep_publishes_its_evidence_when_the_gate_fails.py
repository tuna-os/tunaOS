#!/usr/bin/env python3
"""The desktop contract sweep must publish what it measured, pass or fail.

The sweep runs one job per published variant x desktop cell, pulls the image,
and records both the desktop contract verdict and the criterion 8 silent
omissions verdict. `scripts/gen-matrix-status.py` reads those verdicts out of
the run's `desktop-contract-baseline` artifact.

Two coupled defects put that whole axis in the dark. The upload step sat after
a completeness gate that fails the job whenever any cell is not passing, so a
failing gate skipped the upload; and the reader only accepted artifacts from
runs whose conclusion was "success". The gate had tripped every night since
2026-09-09, and docs/MATRIX-STATUS.md consequently read "**0 of 51** cells
clean (0 read, 51 never read)" — while 51 cell jobs succeeded nightly, each
having actually read its image. Because `no_silent_omissions` is blocking in
.github/green-criteria.yml, that rendered every desktop cell in the composite
table untested.

The verdict and the evidence are separate things. These tests hold them apart.
"""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / ".github" / "workflows" / "desktop-contract-sweep.yml"
SCRIPT = ROOT / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("gen_matrix_status", gms)
_spec.loader.exec_module(gms)


def _baseline_steps() -> list[dict]:
    wf = yaml.safe_load(SWEEP.read_text())
    for job in wf["jobs"].values():
        if job.get("name") == "Baseline":
            return job["steps"]
    raise AssertionError("no job named 'Baseline' in desktop-contract-sweep.yml")


def _upload_index(steps: list[dict]) -> int:
    for i, s in enumerate(steps):
        if "upload-artifact" in str(s.get("uses", "")):
            return i
    raise AssertionError("the Baseline job uploads no artifact")


def _gate_index(steps: list[dict]) -> int:
    for i, s in enumerate(steps):
        if "completeness gate" in str(s.get("run", "")) and "exit 1" in s["run"]:
            return i
    raise AssertionError("the Baseline job no longer runs a completeness gate")


class TheSelectorsAreNotVacuous(unittest.TestCase):
    """tunaOS#1730: a test that selects nothing passes for the wrong reason."""

    def test_the_baseline_job_exists_and_has_steps(self):
        self.assertGreater(len(_baseline_steps()), 1)

    def test_both_the_upload_and_the_gate_are_found(self):
        steps = _baseline_steps()
        # Each raises rather than returning a sentinel, so merely calling them
        # proves the two things these tests order actually exist to be ordered.
        self.assertIsInstance(_upload_index(steps), int)
        self.assertIsInstance(_gate_index(steps), int)


class TheEvidenceOutlivesTheVerdict(unittest.TestCase):

    def test_the_upload_runs_even_when_an_earlier_step_failed(self):
        step = _baseline_steps()[_upload_index(_baseline_steps())]
        self.assertEqual(
            str(step.get("if", "")).strip(), "always()",
            "the baseline artifact must upload unconditionally: it is the only "
            "record of what the 51 cell jobs measured",
        )

    def test_the_completeness_gate_runs_after_the_upload(self):
        steps = _baseline_steps()
        self.assertLess(
            _upload_index(steps), _gate_index(steps),
            "a gate that fails before the upload takes the evidence with it",
        )

    def test_the_gate_still_fails_on_any_unhealthy_cell(self):
        """Publishing evidence must not have softened the verdict."""
        gate = _baseline_steps()[_gate_index(_baseline_steps())]["run"]
        self.assertIn("fail + miss + err + lost > 0", gate)
        self.assertIn("exit 1", gate)

    def test_all_json_is_written_only_after_the_table_reconciles(self):
        """Its presence in the artifact is what downstream readers trust."""
        build = next(s["run"] for s in _baseline_steps()
                     if "does not reconcile" in str(s.get("run", "")))
        reconcile = build.index("does not reconcile")
        publish = build.index("mv reconciled.json all.json")
        self.assertLess(
            reconcile, publish,
            "all.json must appear only past the reconciliation check",
        )


def _run_list(conclusion: str) -> object:
    return [{"databaseId": 9, "createdAt": "2026-09-12T11:52:41Z",
             "status": "completed", "conclusion": conclusion}]


class AFailedSweepIsStillEvidence(unittest.TestCase):

    def setUp(self):
        gms._BASELINE_CACHE = None
        self.addCleanup(setattr, gms, "_BASELINE_CACHE", None)

    def _cells_for(self, conclusion: str) -> list[dict]:
        payload = [{"cell": "skipjack:gnome", "status": "fail",
                    "omissions_status": "pass", "omissions_reason": ""}]

        def fake_download(argv, **kw):
            # `gh run download ... --dir TMP` — write the artifact it fetched.
            tmp = Path(argv[argv.index("--dir") + 1])
            (tmp / "all.json").write_text(json.dumps(payload))
            return subprocess.CompletedProcess(argv, 0, stdout="")

        with mock.patch.object(gms, "gh_json", return_value=_run_list(conclusion)), \
                mock.patch.object(gms.subprocess, "run", side_effect=fake_download):
            cells, _date, _run_id = gms._baseline_cells()
        return cells

    def test_a_failed_run_is_read(self):
        self.assertEqual(len(self._cells_for("failure")), 1)

    def test_a_successful_run_is_still_read(self):
        self.assertEqual(len(self._cells_for("success")), 1)

    def test_a_cancelled_run_is_not_read(self):
        # Cancelled means the measurements may be half-taken. Untested, not clean.
        self.assertEqual(self._cells_for("cancelled"), [])

    def test_a_failed_sweep_still_yields_omission_verdicts(self):
        """The end the whole change exists for."""
        gms._BASELINE_CACHE = (
            [{"cell": "skipjack:gnome", "omissions_status": "pass"},
             {"cell": "sailfin:kde", "omissions_status": "fail"},
             {"cell": "marlin:niri", "omissions_status": "untested"}],
            "2026-09-12", "9",
        )
        out = gms.omissions_results()
        self.assertEqual(out["skipjack:gnome"][0], "success")
        self.assertEqual(out["sailfin:kde"][0], "failure")
        # Untested stays absent: absence of evidence is never a pass (#1730).
        self.assertNotIn("marlin:niri", out)


if __name__ == "__main__":
    unittest.main()
