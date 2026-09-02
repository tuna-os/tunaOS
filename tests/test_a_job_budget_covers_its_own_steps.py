"""A job's timeout must be able to cover the steps inside it.

`timeout-minutes` at the job level and at the step level are independent
budgets, and GitHub enforces both. When the job's is the smaller one the
steps never get to fail on their own terms: the job is cancelled with
every step still inside its limit, and `cancelled` is the same word
Actions uses for a spot reclamation or a user hitting the button. A real
failure and an infrastructure flake become indistinguishable.

That is not hypothetical. `iso-e2e.yml` carried a flat `timeout-minutes: 30`
while its build step declared 60 and its readiness step 20, so every
`source: build` cell died at exactly 30 minutes -- E2E guppy:xfce (job
97638529947) started building at 00:18:40 and was cancelled at 00:48:29.
A six-cell sweep produced no verdict about any cell it ran.

The check is deliberately weak in one direction: a job timeout written as
an expression (`${{ ... && 90 || 30 }}`) passes if ANY branch covers the
steps, because which branch applies depends on inputs this test cannot
evaluate. It still catches the case that matters, where no branch does.
"""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))


def _budgets(value):
    """Every numeric minute budget a `timeout-minutes` value could take."""
    if value is None:
        return []
    if isinstance(value, int):
        return [value]
    return [int(n) for n in re.findall(r"\b(\d+)\b", str(value))]


def _cases():
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text()) or {}
        for job_id, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps") or []
            step_total = sum(
                max(_budgets(s.get("timeout-minutes")), default=0)
                for s in steps
                if isinstance(s, dict)
            )
            if step_total == 0:
                continue  # no step declares a budget; nothing to cover
            yield wf.name, job_id, job.get("timeout-minutes"), step_total


CASES = list(_cases())


@pytest.mark.parametrize(
    "workflow,job_id,job_timeout,step_total",
    CASES,
    ids=[f"{w}:{j}" for w, j, _, _ in CASES],
)
def test_a_job_budget_covers_its_own_steps(workflow, job_id, job_timeout, step_total):
    if job_timeout is None:
        # No job timeout means GitHub's 360-minute default, which is larger
        # than any step budget we write. Nothing to enforce.
        return
    best = max(_budgets(job_timeout), default=0)
    assert best >= step_total, (
        f"{workflow} job '{job_id}': job timeout {job_timeout!r} tops out at "
        f"{best} minutes but its steps declare {step_total}. The job will be "
        f"cancelled with its steps still inside their own limits, and the "
        f"cancellation is indistinguishable from an infrastructure flake."
    )


def test_the_check_has_something_to_check():
    """A parametrized test over an empty list passes while asserting nothing."""
    assert CASES, "no job in .github/workflows declares step-level timeouts"
