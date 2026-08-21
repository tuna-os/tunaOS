#!/usr/bin/env python3
"""Re-dispatch variant nightlies that never started (tuna-os/tunaOS#1933).

A startup failure is a run GitHub refused to begin: zero jobs, zero
duration, conclusion "failure". On 2026-08-21 all 13 variant nightlies
died this way at once, attributed to a `gh-readonly-queue/*` ref that had
been deleted when the PR it belonged to merged the evening before. A whole
night of images, lost silently.

`rerun-infra-failures.yml` cannot recover these, for two independent
reasons, and the second is the fatal one:

  1. It classifies by reading each failed job's log, and bails early when
     there are no failed jobs -- which is exactly the shape of a run that
     never produced any.
  2. It is driven by `workflow_run: [completed]`, and GitHub does not emit
     that event for a run that never started. Verified against its own run
     history: nothing fired for any of the 13.

So recovery here has to be POLLED rather than evented, which is what this
script is. It is deliberately narrow: a run with jobs is a real failure and
must stay red and visible.

Idempotency is structural rather than stateful. A workflow is re-dispatched
only when the startup-failed scheduled run is still the newest run of that
workflow; the dispatch itself then becomes the newest run, so the next
sweep skips it. That also means a human who already re-ran it by hand is
never duplicated.

And the sweep is CAPPED, because the failure it recovers from is a mass one.
The 2026-08-21 event lost all 13 at once, so an uncapped sweep would dispatch
13 full variant builds simultaneously into a 20-concurrent-job ceiling --
recreating exactly the thundering herd the nightly stagger (#1932) exists to
prevent, and starving them all into the same slow failure it was meant to
cure. Recovering two per sweep drains a total loss over the following day
while never putting more than two extra variants in flight, and in the common
case -- one variant lost -- recovery is still immediate. What the cap defers
is reported, never silently dropped.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


# Only the per-variant nightlies. Deliberately not every scheduled workflow:
# re-dispatching an arbitrary workflow because it failed to start is a much
# broader claim than this evidence supports.
# See the module docstring: an uncapped sweep answers a 13-variant loss with
# 13 simultaneous builds, which the job ceiling cannot absorb.
DEFAULT_MAX_DISPATCH = 2

WORKFLOWS = [
    "build-albacore.yml",
    "build-bonito-rawhide.yml",
    "build-bonito.yml",
    "build-flounder-sid.yml",
    "build-flounder.yml",
    "build-grouper.yml",
    "build-guppy.yml",
    "build-gurnard.yml",
    "build-hummingbird.yml",
    "build-marlin.yml",
    "build-sailfin.yml",
    "build-skipjack.yml",
    "build-yellowfin.yml",
]


def latest_scheduled(runs):
    """The newest `schedule` run, or None. `runs` is newest-first."""
    for run in runs:
        if run.get("event") == "schedule":
            return run
    return None


def is_startup_failure(run, job_count):
    """A run that failed without producing a single job.

    Job count is the discriminator, not duration: a run can fail fast for
    real reasons, but a real failure always leaves a job behind.
    """
    return run.get("conclusion") == "failure" and job_count == 0


def has_newer_run(runs, run):
    """Anything newer means this startup failure has already been answered.

    Either by a previous sweep's dispatch or by a human re-running it. This
    is what keeps the sweep idempotent without storing state.
    """
    return any(other["created_at"] > run["created_at"] for other in runs)


def needs_redispatch(runs, job_count):
    """Decide for one workflow, given its runs (newest-first) and the job
    count of its newest scheduled run."""
    run = latest_scheduled(runs)
    if run is None:
        return False
    if not is_startup_failure(run, job_count):
        return False
    return not has_newer_run(runs, run)


def _gh(args):
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout


def runs_for(repo, workflow, limit=20):
    out = _gh([
        "api",
        f"repos/{repo}/actions/workflows/{workflow}/runs?per_page={limit}",
        "--jq",
        "[.workflow_runs[] | {id, event, conclusion, created_at}]",
    ])
    return json.loads(out)


def job_count(repo, run_id):
    out = _gh([
        "api",
        f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=1",
        "--jq",
        ".total_count",
    ])
    return int(out.strip())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--ref", default="main")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be dispatched without dispatching it",
    )
    ap.add_argument(
        "--max-dispatch",
        type=int,
        default=DEFAULT_MAX_DISPATCH,
        help=(
            "most workflows to re-dispatch in one sweep; the rest are "
            "reported and picked up by the next sweep"
        ),
    )
    args = ap.parse_args(argv)

    dispatched, deferred, skipped = [], [], []
    for workflow in WORKFLOWS:
        try:
            runs = runs_for(args.repo, workflow)
        except subprocess.CalledProcessError as exc:
            # One unreadable workflow must not stop the sweep: the whole
            # point is recovering the OTHER twelve.
            print(f"  {workflow}: could not list runs ({exc}); skipping")
            skipped.append(workflow)
            continue

        run = latest_scheduled(runs)
        if run is None:
            print(f"  {workflow}: no scheduled run in the window")
            continue

        count = job_count(args.repo, run["id"])
        if not needs_redispatch(runs, count):
            print(
                f"  {workflow}: run {run['id']} "
                f"conclusion={run['conclusion']} jobs={count} -- no action"
            )
            continue

        if len(dispatched) >= args.max_dispatch:
            # Deferred, not dropped: say so, so a capped sweep never reads as
            # a clean one.
            print(
                f"  {workflow}: run {run['id']} failed with ZERO jobs -- "
                f"DEFERRED, {args.max_dispatch} already dispatched this sweep"
            )
            deferred.append(workflow)
            continue

        print(
            f"  {workflow}: run {run['id']} failed with ZERO jobs and is "
            "still the newest run -- re-dispatching"
        )
        if not args.dry_run:
            _gh([
                "api",
                "--method", "POST",
                f"repos/{args.repo}/actions/workflows/{workflow}/dispatches",
                "-f", f"ref={args.ref}",
            ])
        dispatched.append(workflow)

    print(
        f"\nre-dispatched {len(dispatched)}; deferred {len(deferred)}; "
        f"unreadable {len(skipped)}"
    )
    if dispatched:
        print("  dispatched: " + ", ".join(dispatched))
    if deferred:
        print("  deferred to the next sweep: " + ", ".join(deferred))
    return 0


if __name__ == "__main__":
    sys.exit(main())
