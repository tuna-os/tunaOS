"""Every reusable-workflow call grants what the called workflow's jobs declare.

GitHub checks a called workflow's `permissions` against its caller's grant when
the run starts, before any job runs and whether or not the declaring job would
run: a grant the caller lacks is a startup_failure for the whole run ("The
nested job ... is requesting 'contents: write', but is only allowed 'contents:
read'"). post-build-luks-e2e.yml failed every run from 2026-09-09 that way.

reusable-build-image.yml's live_overlay job declares `actions: write` to
dispatch live-overlay.yml after Promote, and every image build reaches it
through build-variant.yml. One caller left out and that caller's builds never
start. This applies GitHub's rule to every local `uses:` edge in the repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
LEVEL = {"none": 0, "read": 1, "write": 2}


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8")) or {}


def scopes(permissions, every: set[str]) -> dict[str, int] | None:
    """A permissions value as {scope: level}; None when it is not declared."""
    if permissions is None:
        return None
    if permissions in ("read-all", "write-all"):
        return dict.fromkeys(every, LEVEL[permissions.split("-")[0]])
    return {scope: LEVEL[level] for scope, level in (permissions or {}).items()}


def requested(callee: dict, every: set[str]) -> dict[str, int]:
    wanted: dict[str, int] = {}
    blocks = [callee.get("permissions")] + [
        job.get("permissions") for job in (callee.get("jobs") or {}).values()]
    for block in blocks:
        for scope, level in (scopes(block, every) or {}).items():
            wanted[scope] = max(level, wanted.get(scope, 0))
    return wanted


def edges():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        caller = load(path.name)
        for job_id, job in (caller.get("jobs") or {}).items():
            uses = (job or {}).get("uses", "")
            if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
                yield path.name, job_id, job, caller, uses.rsplit("/", 1)[1]


EVERY_SCOPE = {"actions", "attestations", "checks", "contents", "deployments",
               "discussions", "id-token", "issues", "packages", "pages",
               "pull-requests", "repository-projects", "security-events", "statuses"}


@pytest.mark.parametrize("caller,job_id,job,caller_doc,callee",
                         list(edges()), ids=lambda v: v if isinstance(v, str) else "")
def test_the_calling_job_grants_every_scope_the_callee_declares(caller, job_id, job, caller_doc, callee):
    grant = scopes(job.get("permissions"), EVERY_SCOPE)
    if grant is None:
        grant = scopes(caller_doc.get("permissions"), EVERY_SCOPE)
    if grant is None:
        pytest.skip(f"{caller}:{job_id} inherits the repository default, which is not in the tree")
    short = {scope: level for scope, level in requested(load(callee), EVERY_SCOPE).items()
             if grant.get(scope, 0) < level}
    assert not short, (
        f"{caller}:{job_id} calls {callee}, which declares "
        + ", ".join(f"{s}: {[k for k, v in LEVEL.items() if v == lvl][0]}" for s, lvl in short.items())
        + " beyond the caller's grant; GitHub fails that run at startup"
    )
