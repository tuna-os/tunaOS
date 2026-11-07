"""Every `pull_request` workflow must survive a pull request from a fork.

On a `pull_request` event raised from a fork, GitHub hands the job a
read-only GITHUB_TOKEN whatever `permissions:` asks for, and every
repository secret is empty. A workflow that pushes, comments, or uploads with
those credentials does not degrade — it 403s, and `bash -e` turns the 403
into a red check on exactly the population least able to read it: the
first-time external contributor. Hive hit this on its changelog reminder
(kubestellar/hive#4440) and now tests the 403 path explicitly; this repo hit
it on iso-e2e (#1129: empty R2 secrets made rclone fall back to an anonymous
endpoint and fail for 20 minutes on every fork PR).

These tests are the static half of that lesson (epic #2250 item 13). They
do not run the workflows; they prove each one has the SHAPE that survives a
fork:

  * it declares `permissions:` (top level or on every job), so what it needs
    is written down and the read-only downgrade is a visible diff, not a
    surprise;
  * it never uses `pull_request_target` — the trigger that hands secrets to
    untrusted code — unless a reviewed allowlist names it;
  * every step that pushes, comments, opens a PR, or reads a non-GITHUB_TOKEN
    secret is fork-aware: guarded by the event name or the head repo, or
    written to tolerate the failure.

The dynamic half runs the fork-sensitive, act-compatible PR workflows with an
empty secret set. It classifies every other PR workflow with a reviewed reason;
running every image and KVM lane three times proved too expensive in #2604.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# Reviewed exceptions. Empty on purpose; add an entry with the reason.
PULL_REQUEST_TARGET_ALLOWED: dict[str, str] = {}

# Signals that a step can only succeed with write access or real secrets.
WRITE_ACTIONS = re.compile(
    r"git push|gh pr (comment|create|edit|review|merge)|gh issue (comment|create|edit)"
    r"|gh api [^\n]*(--method|-X) ?(POST|PATCH|PUT|DELETE)"
    r"|gh api [^\n]*-F |gh release |actions/github-script"
)
SECRET_REF = re.compile(r"\$\{\{\s*secrets\.(?!GITHUB_TOKEN\b)([A-Za-z0-9_]+)")

# Evidence that the author thought about the fork case.
FORK_GUARDS = (
    "github.event_name != 'pull_request'",
    'github.event_name != "pull_request"',
    "github.event_name == 'workflow_dispatch'",
    "github.event_name == 'push'",
    "head.repo.fork",
    "head.repo.full_name",
    "IS_FORK",
    "no_r2_credentials",
)


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8")) or {}


def _triggers(doc: dict) -> dict:
    on = doc.get("on", doc.get(True, {}))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {k: None for k in on}
    return on or {}


def _pr_workflows() -> list[str]:
    return sorted(
        f.name for f in WORKFLOWS.glob("*.y*ml")
        if "pull_request" in _triggers(_load(f.name))
    )


PR_WORKFLOWS = _pr_workflows()


def test_there_are_pull_request_workflows_to_check():
    assert len(PR_WORKFLOWS) >= 5, PR_WORKFLOWS


@pytest.mark.parametrize("name", PR_WORKFLOWS)
def test_permissions_are_declared(name):
    doc = _load(name)
    if "permissions" in doc:
        return
    jobs = doc.get("jobs") or {}
    missing = [j for j, body in jobs.items()
               if "permissions" not in (body or {}) and "uses" not in (body or {})]
    assert not missing, (
        f"{name}: jobs {missing} run on pull_request with the default token "
        "scope. Declare `permissions:` so the read-only downgrade on fork PRs "
        "is a visible diff against what the job actually needs."
    )


def test_pull_request_target_is_not_used_without_review():
    offenders = []
    for f in WORKFLOWS.glob("*.y*ml"):
        if "pull_request_target" in _triggers(_load(f.name)):
            if f.name not in PULL_REQUEST_TARGET_ALLOWED:
                offenders.append(f.name)
    assert not offenders, (
        f"{offenders} use pull_request_target, which runs with secrets and a "
        "write token against a PR's contents. Add a reviewed reason to "
        "PULL_REQUEST_TARGET_ALLOWED or use pull_request."
    )


def _fork_aware(text: str) -> bool:
    return any(g in text for g in FORK_GUARDS)


def _unguarded_write_steps(name: str) -> list[str]:
    """Steps that need write access or secrets and show no sign of knowing a
    fork PR will not have them."""
    doc = _load(name)
    problems = []
    for job_id, job in (doc.get("jobs") or {}).items():
        job = job or {}
        job_guard = _fork_aware(str(job.get("if", "")))
        steps = job.get("steps") or []
        # A preflight step that decides the fork case once (iso-e2e's
        # `filter` step, #1129) guards every later step that keys off its
        # outputs. Follow that indirection rather than demanding the guard
        # be repeated on each step.
        aware_ids = {
            s.get("id") for s in steps
            if s.get("id") and _fork_aware(
                str(s.get("if", "")) + yaml.dump(s.get("env") or {}) + str(s.get("run", "")))
        }
        for step in steps:
            blob = yaml.dump(step)
            needs_write = bool(WRITE_ACTIONS.search(blob))
            secrets = [m.group(1) for m in SECRET_REF.finditer(blob)]
            if not needs_write and not secrets:
                continue
            cond = str(step.get("if", ""))
            step_text = cond + "\n" + yaml.dump(step.get("env") or {}) + "\n" + str(step.get("run", ""))
            guarded_by_preflight = any(f"steps.{sid}.outputs" in cond for sid in aware_ids)
            if job_guard or guarded_by_preflight or _fork_aware(step_text) \
                    or step.get("continue-on-error"):
                continue
            what = "secrets " + ",".join(sorted(set(secrets))) if secrets else "a write action"
            problems.append(f"{name}: job {job_id!r} step {step.get('name', '?')!r} uses {what}")
    return problems


@pytest.mark.parametrize("name", PR_WORKFLOWS)
def test_write_steps_know_about_forks(name):
    problems = _unguarded_write_steps(name)
    assert not problems, (
        "\n".join(problems)
        + "\n\nOn a fork PR the token is read-only and every secret is empty. "
        "Guard the step (github.event_name, head.repo.fork / full_name), "
        "check for the empty secret before using it, or tolerate the failure "
        "and deliver the result as a job summary instead (see just-fix.yml)."
    )


def test_the_write_detector_recognises_the_shapes_it_guards():
    """Guard the guard: a scanner that matched nothing would pass the test
    above on any tree."""
    assert WRITE_ACTIONS.search("run: |\n  git push -u origin x")
    assert WRITE_ACTIONS.search("gh pr comment 1 --body hi")
    assert WRITE_ACTIONS.search('gh api "repos/$R/issues/$N/comments" -F body=@f')
    assert SECRET_REF.search("${{ secrets.R2_BUCKET }}")
    assert not SECRET_REF.search("${{ secrets.GITHUB_TOKEN }}")
    assert not WRITE_ACTIONS.search("gh api repos/x/pulls/1/files --jq .")


def test_just_fix_reports_the_diff_on_a_pull_request_and_writes_only_on_main():
    """`just fix` runs repository-controlled code, so on a pull request it
    holds a read-only token and reports the drift (job summary, failing
    check, diff artifact) instead of pushing (#3666). The writer runs on a
    push to main only."""
    doc = _load("just-fix.yml")
    jobs = doc["jobs"]
    assert jobs["format-pr"]["if"] == "github.event_name == 'pull_request'"
    assert jobs["fix-main"]["if"] == (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )
    body = (WORKFLOWS / "just-fix.yml").read_text(encoding="utf-8")
    assert "GITHUB_STEP_SUMMARY" in body, "the PR path must deliver the diff somewhere"


# Reviewed exceptions to "a pull_request job holds no write scope". Each
# entry is a job that needs the scope and either checks out no PR code or
# runs it without a persisted credential. A new entry needs a reason a
# reviewer can check.
PR_WRITE_SCOPE_ALLOWED: dict[tuple[str, str], str] = {
    ("drop-bot-review-requests.yml", "drop"): "removes bot review requests via the API; checks out nothing",
    ("pr-nudges.yml", "remind"): "posts a reminder comment; reads PR metadata, checkout does not persist credentials",
    ("test.yml", "coverage-upload"): "id-token: write mints the OIDC token for the coverage upload only",
    ("tuna-pr-images.yml", "tuna_pr_images"): "reusable image build; packages/id-token for the PR image registry",
    ("tuna-pr-images.yml", "canary_cells"): "reusable image build; packages/id-token for the PR image registry",
}
PUSH_ONLY_GUARDS = (
    "github.event_name == 'push'",
    "github.event_name == 'schedule'",
    "github.event_name == 'workflow_dispatch'",
    "github.event_name != 'pull_request'",
)


def _job_write_scopes(doc: dict, job: dict) -> dict[str, str]:
    perms = job.get("permissions", doc.get("permissions"))
    if perms == "write-all":
        return {"*": "write"}
    if not isinstance(perms, dict):
        return {}
    return {k: v for k, v in perms.items() if v == "write"}


def _pr_reachable_jobs(name: str):
    doc = _load(name)
    for job_id, job in (doc.get("jobs") or {}).items():
        job = job or {}
        cond = str(job.get("if", ""))
        # An `||` can re-admit the pull_request event, so only a plain
        # conjunction counts as an exclusion.
        if "||" not in cond and any(g in cond for g in PUSH_ONLY_GUARDS):
            continue
        yield doc, job_id, job


@pytest.mark.parametrize("name", PR_WORKFLOWS)
def test_pull_request_jobs_hold_no_unreviewed_write_scope(name):
    """The untrusted-PR + write-token class (tuna-installer-xfce#57, tunaOS
    #1740, bluefin-cli#1181, just-fix.yml #3666): a job reachable from a
    pull_request event runs PR-controlled code. It must not hold
    `contents: write`, and any other write scope needs a reviewed reason."""
    problems = []
    for doc, job_id, job in _pr_reachable_jobs(name):
        scopes = _job_write_scopes(doc, job)
        if not scopes:
            continue
        if "contents" in scopes or "*" in scopes:
            problems.append(f"{name}: job {job_id!r} holds contents: write on pull_request")
        elif (name, job_id) not in PR_WRITE_SCOPE_ALLOWED:
            problems.append(f"{name}: job {job_id!r} holds {sorted(scopes)} on pull_request")
    assert not problems, (
        "\n".join(problems)
        + "\n\nSplit the writer into a job gated to push/schedule, keep the "
        "pull_request job read-only, or add a reviewed reason to "
        "PR_WRITE_SCOPE_ALLOWED."
    )


@pytest.mark.parametrize("name", PR_WORKFLOWS)
def test_pull_request_jobs_with_write_scope_do_not_persist_credentials(name):
    problems = []
    for doc, job_id, job in _pr_reachable_jobs(name):
        if not _job_write_scopes(doc, job):
            continue
        for step in job.get("steps") or []:
            if str(step.get("uses", "")).startswith("actions/checkout@") and \
                    (step.get("with") or {}).get("persist-credentials") is not False:
                problems.append(f"{name}: job {job_id!r} checkout keeps the credential")
    assert not problems, "\n".join(problems) + (
        "\n\nA write-scoped pull_request job must check out with "
        "`persist-credentials: false`."
    )


@pytest.mark.parametrize("name", PR_WORKFLOWS)
def test_pull_request_jobs_never_push_or_open_prs(name):
    problems = []
    for _doc, job_id, job in _pr_reachable_jobs(name):
        for step in job.get("steps") or []:
            if re.search(r"git push|gh pr create", str(step.get("run", ""))):
                problems.append(f"{name}: job {job_id!r} step {step.get('name', '?')!r}")
    assert not problems, (
        "\n".join(problems)
        + "\n\nOnly a job gated to push/schedule may push a branch or open a PR."
    )


def test_the_pr_write_gate_fails_on_the_old_just_fix_shape():
    """Guard the guard: the single-job, write-token shape #3666 removed must
    trip the checks above."""
    old = yaml.safe_load("""
on: [pull_request, push]
jobs:
  fix:
    permissions: {contents: write, pull-requests: write}
    steps:
      - uses: actions/checkout@abc
        with: {persist-credentials: true}
      - run: git push
""")
    job = old["jobs"]["fix"]
    assert "contents" in _job_write_scopes(old, job)
    assert (job["steps"][0]["with"]["persist-credentials"]) is not False
    assert re.search(r"git push|gh pr create", job["steps"][1]["run"])
