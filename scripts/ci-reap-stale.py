#!/usr/bin/env python3
"""Reap stale workflow runs and expired artifacts through `gh api`.

`just ci-reap-stale` runs this from the scheduled .github/workflows/ci-reaper.yml.

  cancel   runs still queued/in_progress after STALE_QUEUED_HOURS
           (default 6), measured from when they were queued (run_started_at for
           a run that is already executing)
  delete   completed runs that finished more than KEEP_RUN_DAYS (default 14)
           ago
  delete   expired artifacts older than KEEP_RUN_DAYS

Never touched, whatever their age:

  * the newest run of each (workflow, head repository, branch) -- it is the
    run a status badge, a branch's checks and `gh run list` still point at;
  * the run executing this script (GITHUB_RUN_ID);
  * artifacts that belong to a run that is itself kept.

Runs on the default branch or a protected branch are held to the same ages:
a push run younger than the bound is never cancelled or deleted, because both
decisions are age gates. Caches are not touched: they are shared across runs
and expire on their own.

DRY_RUN=1 prints every decision and sends no request that changes anything.

Exit status: 0 when every requested action succeeded or was already moot (the
run finished or disappeared first); 1 when the API could not be read or an
action was refused (for example a token without `actions: write`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

PER_PAGE = 100
MAX_PAGES = 100
# `waiting` is deliberately absent: a run parked on an environment approval is
# waiting for a human, not stuck.
ACTIVE = {"queued", "requested", "pending", "in_progress"}
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


def paged(path: str, key: str) -> list[dict]:
    items: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        joiner = "&" if "?" in path else "?"
        body = json.loads(gh(f"{path}{joiner}per_page={PER_PAGE}&page={page}") or "{}")
        batch = body.get(key, [])
        items.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return items


def group_key(run: dict) -> tuple:
    head_repo = (run.get("head_repository") or {}).get("full_name", "")
    return (run.get("workflow_id"), head_repo, run.get("head_branch"))


def newest_per_group(runs: list[dict]) -> set[int]:
    newest: dict[tuple, dict] = defaultdict(dict)
    for run in runs:
        key = group_key(run)
        current = newest.get(key)
        if not current or (parse_time(run["created_at"]), run["id"]) > (parse_time(current["created_at"]), current["id"]):
            newest[key] = run
    return {run["id"] for run in newest.values()}


def active_age_start(run: dict) -> datetime | None:
    if run.get("status") == "in_progress":
        return parse_time(run.get("run_started_at")) or parse_time(run.get("created_at"))
    return parse_time(run.get("created_at"))


def plan(runs: list[dict], artifacts: list[dict], now: datetime, stale_hours: float, keep_days: float, self_run: int | None) -> dict:
    keep = newest_per_group(runs)
    if self_run is not None:
        keep.add(self_run)
    stale_before = now - timedelta(hours=stale_hours)
    delete_before = now - timedelta(days=keep_days)

    cancel, delete = [], []
    for run in runs:
        if run["id"] in keep:
            continue
        status = run.get("status")
        if status in ACTIVE:
            started = active_age_start(run)
            if started is not None and started < stale_before:
                cancel.append(run)
        elif status == "completed":
            finished = parse_time(run.get("updated_at")) or parse_time(run.get("created_at"))
            if finished is not None and finished < delete_before:
                delete.append(run)

    deleted_ids = {run["id"] for run in delete}
    expired = []
    for artifact in artifacts:
        run_id = (artifact.get("workflow_run") or {}).get("id")
        if not artifact.get("expired") or run_id in keep or run_id in deleted_ids:
            continue
        created = parse_time(artifact.get("created_at"))
        if created is not None and created < delete_before:
            expired.append(artifact)
    return {"cancel": cancel, "delete": delete, "artifacts": expired, "kept": len(keep)}


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

    try:
        runs = paged(f"repos/{repo}/actions/runs", "workflow_runs")
        artifacts = paged(f"repos/{repo}/actions/artifacts", "artifacts")
    except ApiError as exc:
        print(f"could not read {repo} actions state: {exc}", file=sys.stderr)
        return 1

    decisions = plan(runs, artifacts, datetime.now(timezone.utc), stale_hours, keep_days, self_run)
    print(f"{repo}: {len(runs)} runs, {len(artifacts)} artifacts; keeping the newest run of {decisions['kept']} workflow/branch groups")
    print(f"STALE_QUEUED_HOURS={stale_hours:g} KEEP_RUN_DAYS={keep_days:g} DRY_RUN={'1' if dry else '0'}")
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
