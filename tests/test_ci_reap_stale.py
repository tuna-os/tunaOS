"""`just ci-reap-stale` cancels stuck runs and prunes old ones, safely.

The dangers are the mirror image of a cleanup that does too little: cancelling
a build someone is waiting on, deleting the run a branch's checks point at, or
deleting history in a dry run. Each case drives scripts/ci-reap-stale.py as a
subprocess against a stubbed `gh` that serves fixture pages and records every
request that would change anything.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci-reap-stale.py"

spec = importlib.util.spec_from_file_location("ci_reap_stale", SCRIPT)
reaper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reaper)

NOW = datetime.now(timezone.utc)

GH_STUB = r'''#!/usr/bin/env python3
import json, os, sys
from urllib.parse import urlparse, parse_qs

fixture = json.load(open(os.environ["GH_FIXTURE"]))
args = sys.argv[1:]
assert args[0] == "api", args
args = args[1:]
method = "GET"
if args[:1] == ["-X"]:
    method, args = args[1], args[2:]
path = args[0]
if method != "GET":
    with open(os.environ["GH_LOG"], "a") as log:
        log.write(f"{method} {path}\n")
    for needle, message in fixture.get("fail", {}).items():
        if needle in f"{method} {path}":
            sys.stderr.write(message + "\n")
            sys.exit(1)
    sys.exit(0)
with open(os.environ["GH_LOG"], "a") as log:
    log.write(f"GET {path}\n")
if fixture.get("read_error"):
    sys.stderr.write(fixture["read_error"] + "\n")
    sys.exit(1)
url = urlparse(path)
query = parse_qs(url.query)
page, per_page = int(query["page"][0]), int(query["per_page"][0])
key = {"actions/runs": "workflow_runs", "actions/artifacts": "artifacts"}[url.path.split("/", 3)[3]]
items = fixture[key]
print(json.dumps({key: items[(page - 1) * per_page : page * per_page], "total_count": len(items)}))
'''


def iso(delta: timedelta) -> str:
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_record(run_id, *, workflow=1, branch="feature", status="completed", conclusion="success", age=timedelta(days=30), started_age=None, event="push", repo="o/r"):
    return {
        "id": run_id,
        "name": f"wf{workflow}",
        "workflow_id": workflow,
        "head_branch": branch,
        "head_repository": {"full_name": repo},
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "created_at": iso(age),
        "run_started_at": iso(started_age if started_age is not None else age),
        "updated_at": iso(age),
    }


def artifact(artifact_id, run_id, *, expired=True, age=timedelta(days=30)):
    return {"id": artifact_id, "name": f"a{artifact_id}", "expired": expired, "created_at": iso(age), "workflow_run": {"id": run_id}}


class Gh:
    def __init__(self, tmp_path: Path, runs, artifacts=(), fail=None, read_error=None):
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(GH_STUB)
        (self.bin / "gh").chmod(0o755)
        self.log = tmp_path / "gh.log"
        self.fixture = tmp_path / "fixture.json"
        self.fixture.write_text(json.dumps({"workflow_runs": list(runs), "artifacts": list(artifacts), "fail": fail or {}, "read_error": read_error}))

    def run(self, **env_extra) -> subprocess.CompletedProcess:
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "GH_FIXTURE": str(self.fixture),
            "GH_LOG": str(self.log),
            "GITHUB_REPOSITORY": "o/r",
            "HOME": str(self.fixture.parent),
        }
        env.update(env_extra)
        return subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True)

    def writes(self) -> list[str]:
        if not self.log.exists():
            return []
        return sorted(line for line in self.log.read_text().splitlines() if not line.startswith("GET "))


def reap(tmp_path, runs, artifacts=(), **kwargs):
    env = kwargs.pop("env", {})
    gh = Gh(tmp_path, runs, artifacts, **kwargs)
    result = gh.run(**env)
    return gh, result


def test_dry_run_sends_nothing_that_changes_state(tmp_path):
    runs = [
        run_record(1, branch="main", age=timedelta(days=1)),
        run_record(2, branch="main", age=timedelta(days=40)),
        run_record(3, branch="main", status="queued", conclusion=None, age=timedelta(hours=30)),
    ]
    gh, result = reap(tmp_path, runs, [artifact(9, 3)], env={"DRY_RUN": "1"})
    assert result.returncode == 0, result.stderr
    assert gh.writes() == []
    assert "[dry-run] would cancel run 3" in result.stdout
    assert "[dry-run] would delete run 2" in result.stdout
    assert "[dry-run] would delete expired artifact 9" in result.stdout


def test_the_newest_run_per_workflow_and_branch_is_kept_even_when_ancient_or_stuck(tmp_path):
    runs = [
        # main/wf1: the newest is ancient (nothing newer has run) -> kept.
        run_record(10, workflow=1, branch="main", age=timedelta(days=90)),
        run_record(11, workflow=1, branch="main", age=timedelta(days=120)),
        # main/wf2: the newest is stuck queued -> kept, not cancelled.
        run_record(20, workflow=2, branch="main", status="queued", conclusion=None, age=timedelta(hours=48)),
        # The same branch name on a fork is a different group.
        run_record(30, workflow=1, branch="main", age=timedelta(days=100), repo="fork/r"),
    ]
    gh, result = reap(tmp_path, runs)
    assert result.returncode == 0, result.stderr
    assert gh.writes() == ["DELETE repos/o/r/actions/runs/11"]


def test_only_runs_past_the_bounds_are_touched(tmp_path):
    runs = [
        run_record(1, branch="b", age=timedelta(minutes=5)),  # newest of b
        run_record(2, branch="b", status="queued", conclusion=None, age=timedelta(hours=5, minutes=50)),  # queued, under 6h
        run_record(3, branch="b", status="queued", conclusion=None, age=timedelta(hours=6, minutes=10)),  # queued, over
        run_record(4, branch="b", status="in_progress", conclusion=None, age=timedelta(hours=9), started_age=timedelta(hours=1)),  # running 1h
        run_record(5, branch="b", status="in_progress", conclusion=None, age=timedelta(hours=9), started_age=timedelta(hours=7)),  # running 7h
        run_record(6, branch="b", age=timedelta(days=13)),  # completed, inside retention
        run_record(7, branch="b", age=timedelta(days=15)),  # completed, past retention
        run_record(8, branch="b", status="waiting", conclusion=None, age=timedelta(days=3)),  # parked on approval
    ]
    gh, result = reap(tmp_path, runs)
    assert result.returncode == 0, result.stderr
    assert gh.writes() == [
        "DELETE repos/o/r/actions/runs/7",
        "POST repos/o/r/actions/runs/3/cancel",
        "POST repos/o/r/actions/runs/5/cancel",
    ]


def test_default_branch_push_runs_younger_than_the_bound_are_untouched(tmp_path):
    runs = [
        run_record(1, branch="main", event="push", status="in_progress", conclusion=None, age=timedelta(minutes=30)),
        run_record(2, branch="main", event="push", status="queued", conclusion=None, age=timedelta(hours=2)),
        run_record(3, branch="main", event="push", age=timedelta(days=2)),
        run_record(4, branch="main", event="push", age=timedelta(days=13, hours=23)),
        run_record(5, branch="main", event="push", status="queued", conclusion=None, age=timedelta(hours=1)),
    ]
    gh, result = reap(tmp_path, runs)
    assert result.returncode == 0, result.stderr
    assert gh.writes() == []


def test_the_reaper_never_cancels_or_deletes_its_own_run(tmp_path):
    runs = [
        run_record(1, workflow=1, branch="x", age=timedelta(minutes=1)),
        run_record(2, workflow=1, branch="x", status="in_progress", conclusion=None, age=timedelta(hours=8)),
    ]
    own_run = tmp_path / "own"
    own_run.mkdir()
    gh, _ = reap(own_run, runs, env={"GITHUB_RUN_ID": "2"})
    assert gh.writes() == []
    other = tmp_path / "other"
    other.mkdir()
    gh2, _ = reap(other, runs)
    assert gh2.writes() == ["POST repos/o/r/actions/runs/2/cancel"]


def test_only_expired_artifacts_past_retention_of_runs_that_are_not_kept_are_deleted(tmp_path):
    runs = [
        run_record(1, branch="a", age=timedelta(days=60)),  # newest of a: kept
        run_record(2, branch="a", age=timedelta(days=61)),  # deleted with its artifacts
        run_record(3, branch="b", age=timedelta(days=1)),
        run_record(4, branch="b", age=timedelta(days=5)),
    ]
    artifacts = [
        artifact(100, 1),  # run kept -> keep artifact
        artifact(101, 2),  # run deleted -> the run delete takes it; no second request
        artifact(102, 4, age=timedelta(days=20)),  # expired, old, run kept by age -> delete
        artifact(103, 4, expired=False, age=timedelta(days=20)),  # live artifact: never
        artifact(104, 4, age=timedelta(days=3)),  # expired but young
    ]
    gh, result = reap(tmp_path, runs, artifacts)
    assert result.returncode == 0, result.stderr
    assert gh.writes() == [
        "DELETE repos/o/r/actions/artifacts/102",
        "DELETE repos/o/r/actions/runs/2",
    ]


def test_bounds_are_tunable(tmp_path):
    runs = [
        run_record(1, branch="b", age=timedelta(minutes=1)),
        run_record(2, branch="b", status="queued", conclusion=None, age=timedelta(hours=2)),
        run_record(3, branch="b", age=timedelta(days=2)),
    ]
    gh, result = reap(tmp_path, runs, env={"STALE_QUEUED_HOURS": "1", "KEEP_RUN_DAYS": "1"})
    assert result.returncode == 0, result.stderr
    assert gh.writes() == ["DELETE repos/o/r/actions/runs/3", "POST repos/o/r/actions/runs/2/cancel"]


@pytest.mark.parametrize("name,value", [("STALE_QUEUED_HOURS", "0"), ("KEEP_RUN_DAYS", "-3"), ("KEEP_RUN_DAYS", "soon")])
def test_nonsense_bounds_are_refused_before_anything_is_read_or_changed(tmp_path, name, value):
    gh, result = reap(tmp_path, [run_record(1, age=timedelta(days=90)), run_record(2, age=timedelta(days=91))], env={name: value})
    assert result.returncode != 0
    assert gh.writes() == []


def test_every_page_is_read_so_old_runs_on_later_pages_are_found(tmp_path):
    # 250 runs of one workflow on one branch, newest first: only run 1 is kept.
    runs = [run_record(i, branch="busy", age=timedelta(days=20, minutes=i)) for i in range(1, 251)]
    gh, result = reap(tmp_path, runs)
    assert result.returncode == 0, result.stderr
    assert len(gh.writes()) == 249
    assert "DELETE repos/o/r/actions/runs/1" not in gh.writes()
    assert "DELETE repos/o/r/actions/runs/250" in gh.writes()


def test_an_unreadable_api_changes_nothing_and_fails(tmp_path):
    gh, result = reap(tmp_path, [run_record(1, age=timedelta(days=90))], read_error="HTTP 403: Resource not accessible by integration")
    assert result.returncode == 1
    assert gh.writes() == []
    assert "403" in result.stderr


def test_a_run_that_finished_or_vanished_first_is_not_a_failure(tmp_path):
    runs = [
        run_record(1, branch="b", age=timedelta(minutes=1)),
        run_record(2, branch="b", status="queued", conclusion=None, age=timedelta(hours=9)),
        run_record(3, branch="b", age=timedelta(days=30)),
    ]
    fail = {"actions/runs/2/cancel": "gh: Cannot cancel a workflow run that is completed. (HTTP 409)", "runs/3": "gh: Not Found (HTTP 404)"}
    gh, result = reap(tmp_path, runs, fail=fail)
    assert result.returncode == 0, result.stderr
    assert len(gh.writes()) == 2


def test_a_refused_action_is_reported_but_the_rest_still_run(tmp_path):
    runs = [
        run_record(1, branch="b", age=timedelta(minutes=1)),
        run_record(2, branch="b", age=timedelta(days=30)),
        run_record(3, branch="b", age=timedelta(days=31)),
    ]
    gh, result = reap(tmp_path, runs, fail={"runs/2": "gh: Resource not accessible by integration (HTTP 403)"})
    assert result.returncode == 1
    assert gh.writes() == ["DELETE repos/o/r/actions/runs/2", "DELETE repos/o/r/actions/runs/3"]
    assert "FAILED" in result.stderr


def test_without_a_repository_it_refuses_to_guess(tmp_path):
    gh = Gh(tmp_path, [])
    result = gh.run(GITHUB_REPOSITORY="")
    assert result.returncode == 1
    assert not gh.log.exists()


def test_plan_is_pure_and_deterministic():
    runs = [run_record(1, age=timedelta(days=30)), run_record(2, age=timedelta(days=40))]
    first = reaper.plan(runs, [], NOW, 6, 14, None)
    second = reaper.plan(list(reversed(runs)), [], NOW, 6, 14, None)
    assert [r["id"] for r in first["delete"]] == [r["id"] for r in second["delete"]] == [2]


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_the_recipe_dry_runs_end_to_end(tmp_path):
    gh = Gh(tmp_path, [run_record(1, age=timedelta(days=1)), run_record(2, age=timedelta(days=40))])
    env = {
        "PATH": f"{gh.bin}:/usr/bin:/bin",
        "GH_FIXTURE": str(gh.fixture),
        "GH_LOG": str(gh.log),
        "GITHUB_REPOSITORY": "o/r",
        "DRY_RUN": "1",
        "HOME": str(tmp_path),
    }
    result = subprocess.run([shutil.which("just"), "--justfile", str(ROOT / "Justfile"), "ci-reap-stale"], env=env, capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert "[dry-run] would delete run 2" in result.stdout
    assert gh.writes() == []
