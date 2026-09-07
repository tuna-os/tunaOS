"""#2263: 40 jobs classified as infra, one re-run requested, 39 left red (run 33623184875).

The nightly recovery path (`.github/workflows/rerun-infra-failures.yml`)
classifies transient failures and re-runs them once. Re-running a job
re-runs the workflow run that contains it, so every sibling job in that run
answers

    gh: The workflow run containing this job is already running (HTTP 403)

which is the API saying "already handled", not an error. The loop ran under
`set -euo pipefail` with the `gh` call unguarded, so the first 403 exited the
step. On 2026-09-02 that is exactly what happened: `re-running job
100168062054` succeeded, the next one 403'd, the step failed, and the other
39 jobs stayed red on a Sigstore outage the workflow had already diagnosed
correctly.

These tests hold the shape of the fix: the benign refusal is recognised and
counted, an unexpected refusal still fails the step, and a round that
recovered nothing at all is not reported as success.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "rerun-infra-failures.yml"


def rerun_step() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["classify-and-rerun"]["steps"]
    step = next(s for s in steps if s.get("name") == "Re-run failed jobs")
    return step["run"]


def test_an_already_running_refusal_does_not_end_the_round():
    body = rerun_step()
    assert "is already running" in body, (
        "the 403 that means 'a sibling job already re-ran this run' has to be "
        "recognised, or the first one ends the loop"
    )
    # The gh call must be inside a condition, never a bare command whose
    # non-zero exit `set -e` acts on.
    assert re.search(r"if\s+out=\$\(gh api --method POST[^\n]*\)", body), (
        "the re-run request must be captured and tested, not run bare"
    )


def test_an_unexpected_refusal_still_fails_the_step():
    body = rerun_step()
    assert "refused=$((refused + 1))" in body
    assert re.search(r"if \(\(refused > 0\)\); then", body), (
        "a refusal that is not the benign one must still fail loudly: this "
        "workflow is the only thing standing between a transient fault and a "
        "lost night, and a silent no-op looks identical to a recovery"
    )


def test_a_round_that_recovered_nothing_is_not_a_success():
    body = rerun_step()
    assert re.search(r"requested == 0 && covered == 0", body)


def test_every_job_is_attempted_before_the_step_reports():
    """The counters are summarised after the loop, not inside it, so one
    job's outcome cannot short-circuit the others."""
    body = rerun_step()
    loop_end = body.index("done")
    assert body.index("GITHUB_STEP_SUMMARY") > loop_end
    assert body.index("if ((refused > 0))") > loop_end


def test_the_incident_is_named_where_the_fix_lives():
    body = rerun_step()
    assert "33623184875" in body, (
        "the run that showed this is the evidence for the guard; without it "
        "the next reader sees only defensive-looking bookkeeping"
    )
