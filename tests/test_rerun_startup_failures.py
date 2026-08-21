"""The sweeper must recover lost nights and nothing else (tunaOS#1933).

Two failure modes matter and they pull in opposite directions. Re-dispatching
too little loses a whole night of images across 13 variants, silently, which
is what happened on 2026-08-21. Re-dispatching too much papers over real
build failures and burns runner minutes hiding them.

So the discriminator is pinned here: a run with ZERO jobs never started and
is recoverable; a run with any job at all is a real failure and must stay
red. Plus the idempotency property, which is structural rather than stored --
a dispatch becomes the newest run, so the next sweep sees it and stops.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rerun-startup-failures.py"
WORKFLOW = ROOT / ".github" / "workflows" / "rerun-startup-failures.yml"

_spec = importlib.util.spec_from_file_location("rerun_startup", SCRIPT)
sweeper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweeper)


def run(rid, event="schedule", conclusion="failure", created="2026-08-21T02:17:57Z"):
    return {"id": rid, "event": event, "conclusion": conclusion, "created_at": created}


# --- the discriminator ------------------------------------------------------


def test_zero_jobs_and_failed_is_a_startup_failure() -> None:
    """Run 32439363459's exact shape: build-yellowfin, 0 jobs, 0 seconds."""
    assert sweeper.is_startup_failure(run(32439363459), 0)


def test_a_failure_with_jobs_is_a_real_failure() -> None:
    """The property that stops this papering over broken builds."""
    assert not sweeper.is_startup_failure(run(1), 30)


def test_a_successful_run_with_no_jobs_is_not_recovered() -> None:
    assert not sweeper.is_startup_failure(run(1, conclusion="success"), 0)


# --- picking the run to judge -----------------------------------------------


def test_latest_scheduled_ignores_dispatches_and_pushes() -> None:
    runs = [
        run(3, event="workflow_dispatch", created="2026-08-21T05:00:00Z"),
        run(2, event="push", created="2026-08-21T04:00:00Z"),
        run(1, event="schedule", created="2026-08-21T02:00:00Z"),
    ]
    assert sweeper.latest_scheduled(runs)["id"] == 1


def test_latest_scheduled_is_none_when_never_scheduled() -> None:
    assert sweeper.latest_scheduled([run(1, event="workflow_dispatch")]) is None


# --- the end-to-end decision ------------------------------------------------


def test_a_lost_night_is_redispatched() -> None:
    runs = [run(32439363459)]
    assert sweeper.needs_redispatch(runs, 0)


def test_a_real_failure_is_left_red() -> None:
    assert not sweeper.needs_redispatch([run(1)], 42)


def test_a_green_nightly_is_left_alone() -> None:
    assert not sweeper.needs_redispatch([run(1, conclusion="success")], 30)


def test_the_sweep_is_idempotent() -> None:
    """A dispatch becomes the newest run, so the next sweep must stop.

    Without this the sweeper re-dispatches the same lost night on every
    tick, which is the runaway the single-retry rule exists to prevent.
    """
    failed = run(1, created="2026-08-21T02:17:57Z")
    assert sweeper.needs_redispatch([failed], 0)

    after_dispatch = [
        run(2, event="workflow_dispatch", conclusion=None,
            created="2026-08-21T07:00:00Z"),
        failed,
    ]
    assert not sweeper.needs_redispatch(after_dispatch, 0)


def test_a_human_rerun_is_not_duplicated() -> None:
    runs = [
        run(2, event="workflow_dispatch", conclusion="success",
            created="2026-08-21T06:00:00Z"),
        run(1, created="2026-08-21T02:17:57Z"),
    ]
    assert not sweeper.needs_redispatch(runs, 0)


# --- scope ------------------------------------------------------------------


def test_every_variant_nightly_is_swept() -> None:
    """A variant with a cron but no sweeper entry is a silent hole."""
    scheduled = set()
    for path in (ROOT / ".github" / "workflows").glob("build-*.yml"):
        if path.stem[len("build-"):] in {"variant", "flavor", "toolchain"}:
            continue
        doc = yaml.safe_load(path.read_text())
        triggers = doc.get("on", doc.get(True)) or {}
        if not isinstance(triggers, dict) or not triggers.get("schedule"):
            continue
        crons = [s["cron"].strip() for s in triggers["schedule"]]
        # Daily nightlies only; the weekly Arch base rebuild is out of scope.
        if any(c.endswith("* * *") for c in crons):
            scheduled.add(path.name)
    assert scheduled == set(sweeper.WORKFLOWS)


def test_the_sweeper_runs_often_enough_to_catch_every_slot() -> None:
    """The stagger spreads nightlies across the whole clock, so a daily sweep
    would leave a late-slot startup failure sitting for most of a day."""
    doc = yaml.safe_load(WORKFLOW.read_text())
    triggers = doc.get("on", doc.get(True))
    crons = [s["cron"].strip() for s in triggers["schedule"]]
    assert crons, "the sweep must be scheduled; nothing else notices"
    hours = [c.split()[1] for c in crons]
    assert all(h == "*" or h.startswith("*/") for h in hours), (
        f"expected a sub-daily sweep (hour field '*' or '*/N'), got {crons}"
    )
