#!/usr/bin/env python3
"""Reap stale workflow runs and expired artifacts through `gh api`.

`just ci-reap-stale` runs this from the scheduled .github/workflows/ci-reaper.yml.

  cancel   runs still queued/in_progress after STALE_QUEUED_HOURS
           (default 6), measured from when they were queued (run_started_at for
           a run that is already executing), and only when the API shows a
           newer run of the same group
  delete   (only with REAP_DELETE=1; off by default because run logs are
           cited as evidence) completed runs that finished more than
           KEEP_RUN_DAYS (default 14) ago, and expired artifacts older than
           KEEP_RUN_DAYS

Never touched, whatever their age:

  * the newest run of each (workflow, head repository, branch) -- it is the
    run a status badge, a branch's checks and `gh run list` still point at;
  * the run executing this script (GITHUB_RUN_ID);
  * artifacts that belong to a run that is itself kept, or to a run missing
    from the inventory.

Every decision is made from a complete listing. Cancelling reads the active
runs by status, and a stale run is cancelled only when the newest page of its
workflow on its branch holds a newer run of its group. Deleting reads every
run and every artifact. When a listing stops early (MAX_PAGES, or GitHub's
1,000-result cap on a filtered listing) or returns fewer items than its
total_count, the script changes nothing and exits 1: a run missing from a
partial inventory can be the newest of its group.

Runs on the default branch or a protected branch are held to the same ages:
a push run younger than the bound is never cancelled or deleted, because both
decisions are age gates. Caches are not touched: they are shared across runs
and expire on their own.

DRY_RUN=1 prints every decision and sends no request that changes anything.

Exit status: 0 when every requested action succeeded or was already moot (the
run finished or disappeared first); 1 when the API could not be read in full
or an action was refused (for example a token without `actions: write`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

PER_PAGE = 100
MAX_PAGES = 100
# `waiting` is deliberately absent: a run parked on an environment approval is
# waiting for a human, not stuck.
ACTIVE = ("queued", "requested", "pending", "in_progress")
# `gh api` reports HTTP failures on stderr; these mean the target is already
# gone or already finished, which is the outcome we wanted.
MOOT = ("HTTP 404", "HTTP 409", "HTTP 410")


class ApiError(RuntimeError):
    pass


def gh(*args: str) -> str:
    result = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise ApiError((result.stderr or result.stdout).strip() or f"gh api {' '.join(args)} failed")
    return result.stdout


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_page(path: str, page: int) -> dict:
    joiner = "&" if "?" in path else "?"
    return json.loads(gh(f"{path}{joiner}per_page={PER_PAGE}&page={page}") or "{}")


def paged(path: str, key: str) -> list[dict]:
    """Every item of a listing, or ApiError when the listing cannot be read in full."""
    items: list[dict] = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        body = get_page(path, page)
        batch = body.get(key, [])
        if isinstance(body.get("total_count"), int):
            total = body["total_count"]
        items.extend(batch)
        if len(batch) < PER_PAGE:
            break
    else:
        raise ApiError(f"{path}: more than {MAX_PAGES} pages of {key}; refusing to act on a truncated list")
    if total is not None and len(items) < total:
        raise ApiError(f"{path}: read {len(items)} of {total} {key}; refusing to act on a truncated list")
    return items


def group_key(run: dict) -> tuple:
    head_repo = (run.get("head_repository") or {}).get("full_name", "")
    return (run.get("workflow_id"), head_repo, run.get("head_branch"))


def order_key(run: dict) -> tuple:
    return (parse_time(run["created_at"]), run["id"])


def newest_per_group(runs: list[dict]) -> set[int]:
    newest: dict[tuple, dict] = defaultdict(dict)
    for run in runs:
        key = group_key(run)
        current = newest.get(key)
        if not current or order_key(run) > order_key(current):
            newest[key] = run
    return {run["id"] for run in newest.values()}


def active_age_start(run: dict) -> datetime | None:
    if run.get("status") == "in_progress":
        return parse_time(run.get("run_started_at")) or parse_time(run.get("created_at"))
    return parse_time(run.get("created_at"))


def stale_active(active: list[dict], now: datetime, stale_hours: float, self_run: int | None) -> list[dict]:
    """Active runs past the bound, except this script's own run."""
    stale_before = now - timedelta(hours=stale_hours)
    stale = {}
    for run in active:
        if run["id"] == self_run or run.get("status") not in ACTIVE:
            continue
        started = active_age_start(run)
        if started is not None and started < stale_before:
            stale[run["id"]] = run
    return [stale[run_id] for run_id in sorted(stale)]


def has_newer_run(repo: str, run: dict) -> bool:
    """True only when the API shows a newer run of the same group as `run`.

    Reads the newest page of the run's workflow on its branch. A run with no
    workflow or branch, or a page with no newer run of the same head
    repository, gives False: `run` may be the newest of its group, and the
    newest run is never cancelled.
    """
    workflow, branch = run.get("workflow_id"), run.get("head_branch")
    if workflow is None or not branch:
        return False
    body = get_page(f"repos/{repo}/actions/workflows/{workflow}/runs?branch={quote(branch, safe='')}", 1)
    return any(group_key(other) == group_key(run) and order_key(other) > order_key(run) for other in body.get("workflow_runs", []))


def plan_delete(runs: list[dict], artifacts: list[dict], now: datetime, keep_days: float, self_run: int | None) -> dict:
    """Completed runs and expired artifacts past retention, from a complete inventory."""
    keep = newest_per_group(runs)
    if self_run is not None:
        keep.add(self_run)
    delete_before = now - timedelta(days=keep_days)

    delete = {}
    for run in runs:
        if run["id"] in keep or run.get("status") != "completed":
            continue
        finished = parse_time(run.get("updated_at")) or parse_time(run.get("created_at"))
        if finished is not None and finished < delete_before:
            delete[run["id"]] = run

    known = {run["id"] for run in runs}
    expired = []
    for artifact in artifacts:
        run_id = (artifact.get("workflow_run") or {}).get("id")
        if not artifact.get("expired") or run_id not in known or run_id in keep or run_id in delete:
            continue
        created = parse_time(artifact.get("created_at"))
        if created is not None and created < delete_before:
            expired.append(artifact)
    return {"delete": [delete[run_id] for run_id in sorted(delete)], "artifacts": expired, "kept": len(keep)}


def describe(run: dict) -> str:
    return f"run {run['id']} {run.get('name') or run.get('path', '')} [{run.get('head_branch')}] {run.get('status')}/{run.get('conclusion')} {run.get('created_at')}"


def apply(repo: str, decisions: dict, dry: bool) -> int:
    failures = 0

    def request(label: str, method: str, path: str) -> None:
        nonlocal failures
        if dry:
            print(f"[dry-run] would {label}")
            return
        try:
            gh("-X", method, path)
            print(f"{label}: done")
        except ApiError as exc:
            if any(code in str(exc) for code in MOOT):
                print(f"{label}: already moot ({str(exc).splitlines()[0]})")
            else:
                failures += 1
                print(f"{label}: FAILED ({str(exc).splitlines()[0]})", file=sys.stderr)

    for run in decisions["cancel"]:
        request(f"cancel {describe(run)}", "POST", f"repos/{repo}/actions/runs/{run['id']}/cancel")
    for run in decisions["delete"]:
        request(f"delete {describe(run)}", "DELETE", f"repos/{repo}/actions/runs/{run['id']}")
    for artifact in decisions["artifacts"]:
        request(f"delete expired artifact {artifact['id']} {artifact.get('name')} {artifact.get('created_at')}", "DELETE", f"repos/{repo}/actions/artifacts/{artifact['id']}")
    return failures


def number(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise SystemExit(f"{name} must be a number, got {raw!r}")
    if value <= 0:
        raise SystemExit(f"{name} must be positive, got {raw!r}")
    return value


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("GITHUB_REPOSITORY is not set (expected owner/name)", file=sys.stderr)
        return 1
    stale_hours = number("STALE_QUEUED_HOURS", 6)
    keep_days = number("KEEP_RUN_DAYS", 14)
    dry = os.environ.get("DRY_RUN", "") in {"1", "true", "yes"}
    self_run = int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID", "").isdigit() else None
    # Deleting history is destructive and the logs are cited as evidence
    # (receipts, PR bodies), so it is opt-in; cancelling stuck runs is not.
    delete_history = os.environ.get("REAP_DELETE", "") in {"1", "true", "yes"}
    now = datetime.now(timezone.utc)

    # Read everything and decide before changing anything: a read that fails
    # or comes back truncated leaves the repository exactly as it was.
    decisions = {"cancel": [], "delete": [], "artifacts": []}
    try:
        active = [run for status in ACTIVE for run in paged(f"repos/{repo}/actions/runs?status={status}", "workflow_runs")]
        stale = stale_active(active, now, stale_hours, self_run)
        decisions["cancel"] = [run for run in stale if has_newer_run(repo, run)]
        print(f"{repo}: {len(active)} active runs, {len(stale)} past STALE_QUEUED_HOURS, {len(stale) - len(decisions['cancel'])} of those kept as the newest run of their workflow/branch")
        if delete_history:
            runs = paged(f"repos/{repo}/actions/runs", "workflow_runs")
            artifacts = paged(f"repos/{repo}/actions/artifacts", "artifacts")
            decisions.update(plan_delete(runs, artifacts, now, keep_days, self_run))
            print(f"{repo}: {len(runs)} runs, {len(artifacts)} artifacts; keeping the newest run of {decisions['kept']} workflow/branch groups")
    except ApiError as exc:
        print(f"could not read {repo} actions state in full; nothing was changed: {exc}", file=sys.stderr)
        return 1

    print(f"STALE_QUEUED_HOURS={stale_hours:g} KEEP_RUN_DAYS={keep_days:g} DRY_RUN={'1' if dry else '0'} REAP_DELETE={'1' if delete_history else '0'}")
    print(f"to cancel: {len(decisions['cancel'])}, runs to delete: {len(decisions['delete'])}, expired artifacts to delete: {len(decisions['artifacts'])}")
    failures = apply(repo, decisions, dry)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write(
                f"### CI reaper{' (dry run)' if dry else ''}\n\n"
                f"| cancel stale | delete old runs | delete expired artifacts | failures |\n|---|---|---|---|\n"
                f"| {len(decisions['cancel'])} | {len(decisions['delete'])} | {len(decisions['artifacts'])} | {failures} |\n"
            )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
