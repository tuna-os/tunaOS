"""ISO-building workflows must collapse superseded PR runs, but not sweeps.

A `pull_request` paths filter is evaluated against the PR's WHOLE diff, not
the pushed commit. So once a long-lived branch touches one of the watched
paths, every later push to that PR re-triggers the workflow however
unrelated the change. For a ~25-minute ISO build on a RunsOn EC2 instance
that is a real bill: this branch touches `live-iso/**`, and all eight of
one night's pushes started a fresh build while the previous one ran to
completion.

`cancel-in-progress` fixes that. The subtlety is the GROUP KEY. The repo's
usual form is `<name>-${{ github.ref }}`, and on these two workflows that
would be actively harmful: a multi-cell sweep dispatches several runs
against ONE branch, so they would all share a group and cancel each other
down to the last one — a sweep that silently measures a single cell. Two
of those were already lost to a job-budget bug this session; losing them
to a concurrency key would look identical from the outside.

So the group must vary by run for workflow_dispatch and be shared for
pull_request, and this test pins both halves.
"""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
# The two that build an ISO on a schedule a human did not ask for: they run
# on `pull_request`, so they are the ones a push storm can multiply.
EXPENSIVE = ["live-iso-bootc.yml", "iso-e2e.yml"]


def _concurrency(name):
    doc = yaml.safe_load((WORKFLOWS / name).read_text()) or {}
    return doc.get("concurrency")


@pytest.mark.parametrize("workflow", EXPENSIVE)
def test_it_cancels_superseded_runs(workflow):
    c = _concurrency(workflow)
    assert c, f"{workflow} has no concurrency block; every PR push starts another ISO build"
    assert c.get("cancel-in-progress") is True, (
        f"{workflow} declares a concurrency group but not cancel-in-progress, "
        f"so superseded runs still run to completion — the group alone only queues them."
    )


@pytest.mark.parametrize("workflow", EXPENSIVE)
def test_a_dispatched_sweep_does_not_cancel_itself(workflow):
    """The group must vary per run for workflow_dispatch.

    Asserted on the expression rather than a fixed string, so any key that
    distinguishes dispatches passes and any key that does not fails.
    """
    group = _concurrency(workflow)["group"]
    assert "github.run_id" in group, (
        f"{workflow}'s concurrency group is {group!r}. Without a per-run "
        f"component for workflow_dispatch, the cells of a multi-cell sweep "
        f"share one branch, land in one group, and cancel each other."
    )
    assert "workflow_dispatch" in group, (
        f"{workflow}'s group uses run_id unconditionally ({group!r}), which "
        f"would give every pull_request push its own group too — that is the "
        f"same as having no concurrency at all."
    )


@pytest.mark.parametrize("workflow", EXPENSIVE)
def test_pr_pushes_share_one_group(workflow):
    """Two pushes to the same PR must land in the same group.

    Evaluates the ternary the way GitHub does, for both event types, and
    asserts the resulting keys collide for pull_request and differ for
    dispatch. Checking the string alone would pass on an expression that
    reads plausibly and resolves wrong.
    """
    group = _concurrency(workflow)["group"]

    def resolve(event, run_id, ref="refs/heads/x"):
        out = group.replace("${{ github.ref }}", ref)
        # ${{ A && B || C }} -> B when A else C
        m = re.search(
            r"\$\{\{\s*github\.event_name == '(\w+)'\s*&&\s*github\.run_id\s*\|\|\s*github\.event_name\s*\}\}",
            out,
        )
        assert m, f"unrecognised group expression: {group!r}"
        return out[: m.start()] + (run_id if event == m.group(1) else event) + out[m.end() :]

    assert resolve("pull_request", "1") == resolve("pull_request", "2"), (
        "two pushes to the same PR resolve to different groups, so neither cancels the other"
    )
    assert resolve("workflow_dispatch", "1") != resolve("workflow_dispatch", "2"), (
        "two dispatched sweep cells resolve to the same group and would cancel each other"
    )
