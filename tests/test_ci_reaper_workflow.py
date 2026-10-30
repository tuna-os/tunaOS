"""The reaper workflow is scheduled, least-privilege and dry-run by default.

The reaping rules are tested against a stubbed `gh` in test_ci_reap_stale.py.
This file holds the properties of the workflow that carries them: it can
delete run history, so a manual run must preview first and only the one job
that needs `actions: write` may hold it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/ci-reaper.yml").read_text())
TRIGGERS = WORKFLOW.get("on", WORKFLOW.get(True))


def test_it_runs_daily_and_on_demand():
    crons = [entry["cron"] for entry in TRIGGERS["schedule"]]
    assert len(crons) == 1 and re.fullmatch(r"\d+ \d+ \* \* \*", crons[0]), crons
    assert "workflow_dispatch" in TRIGGERS


def test_a_manual_run_previews_by_default():
    dry_run = TRIGGERS["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["type"] == "boolean" and dry_run["default"] is True


def test_write_access_is_confined_to_the_job_that_reaps():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert WORKFLOW["jobs"]["reap"]["permissions"]["actions"] == "write"
    assert not any("actions" in (job.get("permissions") or {}) for name, job in WORKFLOW["jobs"].items() if name != "reap")


def test_overlapping_reaps_are_serialised_not_cancelled():
    assert WORKFLOW["concurrency"]["group"]
    assert WORKFLOW["concurrency"]["cancel-in-progress"] is False


def test_the_reap_step_goes_through_the_justfile_and_a_scheduled_run_acts():
    steps = WORKFLOW["jobs"]["reap"]["steps"]
    reap = next(step for step in steps if "ci-reap-stale" in step.get("run", ""))
    assert reap["run"].strip() == "just ci-reap-stale"
    # A schedule has no inputs; the expression must still resolve to a real
    # run (DRY_RUN=0) there, and to a preview for a manual dispatch.
    assert reap["env"]["DRY_RUN"].startswith("${{ github.event_name == 'workflow_dispatch' && inputs.dry_run")
    assert reap["env"]["DRY_RUN"].endswith("&& '1' || '0' }}")


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_the_recipe_it_calls_exists():
    just = shutil.which("just")
    summary = subprocess.run([just, "--justfile", str(ROOT / "Justfile"), "--summary"], capture_output=True, text=True, cwd=ROOT)
    assert summary.returncode == 0, summary.stderr
    assert {"ci-reap-stale", "ci-cleanup"} <= set(summary.stdout.split())
