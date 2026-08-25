"""No workflow may push straight to `main`. The rule forbids it.

`installer-smoke.yml`'s screenshot-gallery job ended in

    git pull --rebase origin main
    git push origin HEAD:main

and `main` is protected by a repository rule:

    remote: error: GH013: Repository rule violations found for refs/heads/main.
    remote: - Changes must be made through the merge queue
    ! [remote rejected] HEAD -> main (push declined due to repository rule violations)

That is run 32704425971, and the interesting part is WHY it took until then.
The step is gated on `staged != '0'`, and no flavor had ever produced
walkthrough frames, so the push had never once executed. gnome going green is
what first made it run. A gate that has never run is not a gate that passes,
and this file exists so the next one is caught by the suite instead of by a
rejected push months later.

`matrix-status.yml` already had the answer and even the comment explaining it
("Needed to open the refresh PR; `main` only accepts merge-queue changes"):
one long-lived branch, force-pushed, PR opened once, auto-merge armed. The
screenshot job now does the same thing, so both automation writers share a
shape rather than each inventing one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# `HEAD:main`, `origin main`, `+HEAD:refs/heads/main` and friends. Deliberately
# broad: the point is that no automation writes to the protected branch.
PUSH_TO_MAIN = re.compile(
    r"git\s+push[^\n|;&]*\b(?:HEAD|[\w./-]+)?:?(?:refs/heads/)?main\b"
)


def workflow_files():
    return sorted(WORKFLOWS.glob("*.y*ml"))


def test_there_are_workflows_to_scan():
    """A sweep that matches no file passes for the wrong reason."""
    assert workflow_files(), "no workflow files found"


def test_the_pattern_recognises_the_push_it_was_written_for():
    """Guard the regex itself against silently matching nothing."""
    assert PUSH_TO_MAIN.search("          git push origin HEAD:main")
    assert PUSH_TO_MAIN.search("git push origin HEAD:refs/heads/main")
    # And must not fire on the legitimate branch push.
    assert not PUSH_TO_MAIN.search('git push --force origin "$BRANCH"')
    assert not PUSH_TO_MAIN.search("git pull --rebase origin main")


def test_no_workflow_pushes_to_main():
    offenders = []
    for f in workflow_files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # a comment quoting the bad command is documentation
            if PUSH_TO_MAIN.search(line):
                offenders.append(f"{f.name}:{i}: {stripped}")
    assert not offenders, (
        "these push directly to a branch that only accepts merge-queue "
        "changes; open a PR and arm auto-merge, as matrix-status.yml does: "
        + "; ".join(offenders)
    )


def test_the_screenshot_job_can_actually_open_a_pr():
    """contents:write alone cannot open one — the fix needs the scope too."""
    doc = yaml.safe_load((WORKFLOWS / "installer-smoke.yml").read_text(encoding="utf-8"))
    perms = doc["jobs"]["publish-screenshots"]["permissions"]
    assert perms.get("contents") == "write", perms
    assert perms.get("pull-requests") == "write", perms


def test_the_screenshot_job_arms_auto_merge():
    """A PR from the Actions token starts no checks of its own; without
    auto-merge the refresh sits forever waiting for a human."""
    doc = yaml.safe_load((WORKFLOWS / "installer-smoke.yml").read_text(encoding="utf-8"))
    body = yaml.dump(doc["jobs"]["publish-screenshots"])
    assert "gh pr create" in body
    assert "gh pr merge --auto" in body
