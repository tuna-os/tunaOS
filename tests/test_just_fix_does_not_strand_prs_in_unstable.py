"""A cancelled duplicate check run must not hold every PR in UNSTABLE.

`Just Fix` reformats code. It used to trigger on an unfiltered `push` *and*
on `pull_request`, which produces two runs for the same head SHA whenever a
PR branch is pushed. The concurrency group cancels one of them -- and a
cancelled check run stays attached to that SHA, where GitHub's merge-state
computation counts it as non-success.

The consequence was not a failing check, which someone would have noticed.
It was every PR sitting in `mergeStateStatus: UNSTABLE` with a green-looking
checks list, which quietly stalls auto-merge and the queue paths that key off
merge state. Automation PRs then accumulate unmerged -- the README build
matrix sat at a stale 6/142 for nine hours on 08-16 for exactly this reason,
while the real figure was 84/142 (#1790).

The `pull_request` event covers PR branches at the same head SHA, so nothing
stops being formatted; the duplicate simply stops being created.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/just-fix.yml"


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def triggers(workflow):
    # PyYAML resolves the bare key `on:` to the boolean True.
    return workflow[True]


def test_push_does_not_fire_on_feature_branches(triggers):
    """An unfiltered push duplicates the pull_request run on the same SHA."""
    push = triggers["push"]
    assert isinstance(push, dict) and push.get("branches"), (
        "`push` has no branch filter, so every feature-branch push races the "
        "pull_request event for the same head SHA"
    )
    assert push["branches"] == ["main"]


def test_pull_requests_are_still_formatted(triggers):
    """Removing the duplicate must not remove the coverage.

    If this went too, PR branches would stop being formatted entirely -- a
    worse outcome than the merge-state problem being fixed.
    """
    assert "pull_request" in triggers


def test_the_two_triggers_still_share_a_concurrency_group(workflow):
    """Main-push and PR runs for one branch remain one unit of work.

    The group is still keyed on the branch, so a rapid series of pushes to
    main collapses as before. Only the cross-event duplicate is gone.
    """
    group = workflow["concurrency"]["group"]
    assert "head_ref" in group and "ref_name" in group


def test_the_reason_is_recorded_next_to_the_trigger():
    """A bare `branches: [main]` invites someone to widen it again.

    The failure it prevents is invisible -- a green checks list with a stuck
    merge state -- so the next reader needs the reason in front of them.
    """
    body = WORKFLOW.read_text()
    head = body[: body.index("jobs:")]
    assert "#1790" in head, "the issue is not cited next to the trigger"
    assert "UNSTABLE" in head, "the comment does not name the state this prevents"
    assert "pull_request" in head, (
        "the comment does not say PR branches are still covered, which is the "
        "first thing someone will worry about"
    )
