"""The README build-matrix snapshot has to be able to land.

.github/scripts/update-build-status.sh regenerates the table between the
build-status markers in README.md, and it works. What did not work was
getting the result into main: the workflow committed and ran a bare
`git push`, and main is protected by a ruleset that refuses anything not
coming through the merge queue.

    remote: - Changes must be made through the merge queue
    ! [remote rejected] main -> main (push declined due to repository rule
      violations)

That failed on every scheduled run from 2026-08-08 through 2026-08-12
(and earlier), so the table froze -- every row still dated 2026-07-14/15 a
month later, calling variants blocked that had since been fixed. The job
did go red, but the artifact people actually read is the table, and a
stale table is worse than a missing one because nobody doubts it.

matrix-status.yml hit this rule first and switched to pushing a branch and
opening a PR. These tests pin that this workflow does the same, so the
snapshot cannot silently freeze again.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/update-build-status.yml"
GENERATOR = ROOT / ".github/scripts/update-build-status.sh"
DEFAULT_BRANCH = "main"


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def run_blocks(workflow):
    return [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "run" in step
    ]


def test_the_generator_it_drives_still_exists(workflow, run_blocks):
    assert GENERATOR.exists(), f"{GENERATOR} is gone; the workflow drives nothing"
    assert any(
        "update-build-status.sh" in block for block in run_blocks
    ), "the workflow no longer invokes the generator"


def test_nothing_pushes_straight_at_the_default_branch(run_blocks):
    forbidden = (
        f"git push origin {DEFAULT_BRANCH}",
        f"git push origin HEAD:{DEFAULT_BRANCH}",
    )
    for block in run_blocks:
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # the comment explaining the bug quotes the old push
            for pattern in forbidden:
                assert pattern not in stripped, (
                    f"{pattern!r} targets the protected default branch; the "
                    "ruleset rejects it and the snapshot silently freezes"
                )
            # A bare `git push` is the original bug: checkout leaves the job on
            # the default branch, so it resolves to exactly the same thing.
            assert stripped != "git push", (
                "a bare `git push` runs on the branch checkout left behind -- "
                f"{DEFAULT_BRANCH} -- and the ruleset rejects it"
            )


def test_the_refresh_lands_through_a_pull_request(run_blocks):
    joined = "\n".join(run_blocks)
    assert "gh pr create" in joined, (
        "the refreshed snapshot must be proposed as a PR; the merge queue is "
        "the only way into the default branch"
    )
    assert "git push --force origin" in joined or "git push -u origin" in joined, (
        "the PR needs a branch pushed for it"
    )


def test_the_workflow_may_open_that_pull_request(workflow):
    permissions = workflow.get("permissions") or {}
    assert permissions.get("pull-requests") == "write", (
        "`gh pr create` needs pull-requests: write; without it the refresh "
        f"fails just as surely as the rejected push did (got {permissions!r})"
    )


def test_the_refresh_commit_does_not_skip_ci(run_blocks):
    # Harmless on a direct push, fatal on a queued PR: the required checks the
    # merge queue waits for never start, so the refresh sits open forever.
    for block in run_blocks:
        for line in block.splitlines():
            if line.strip().startswith("#"):
                continue
            if "git commit" in line:
                assert "[skip ci]" not in line, (
                    "[skip ci] on a PR commit suppresses the checks the merge "
                    "queue is waiting for, so the refresh never merges"
                )


def test_the_readme_still_has_the_markers_the_generator_writes_between():
    readme = (ROOT / "README.md").read_text()
    for marker in ("<!-- build-status:start -->", "<!-- build-status:end -->"):
        assert marker in readme, (
            f"{marker} is missing from README.md; the generator has nothing to "
            "replace and the refresh PR would be empty forever"
        )
