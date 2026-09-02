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


# --- the cap ----------------------------------------------------------------


def _all_lost_transport(posts):
    """Every workflow showing the 2026-08-21 shape: failed, zero jobs."""
    import json as _json

    def gh(args):
        joined = " ".join(args)
        if "--method" in args:
            posts.append(joined)
            return ""
        if "/runs?per_page" in joined:
            return _json.dumps(
                [{
                    "id": 999,
                    "event": "schedule",
                    "conclusion": "failure",
                    "created_at": "2026-08-21T02:17:57Z",
                }]
            )
        if "/jobs?per_page" in joined:
            return "0\n"
        return ""

    return gh


def test_a_total_loss_does_not_become_a_thundering_herd(monkeypatch) -> None:
    """The regression this cap exists for.

    Every variant's full build alone exceeds the 20-concurrent-job ceiling,
    which is why the nightlies are staggered at all (#1932). An uncapped
    sweep answers a 13-variant loss with 13 simultaneous builds and starves
    them into the same slow failure it was meant to cure.
    """
    posts = []
    monkeypatch.setattr(sweeper, "_gh", _all_lost_transport(posts))
    sweeper.main(["--repo", "tuna-os/tunaOS"])
    assert len(posts) == sweeper.DEFAULT_MAX_DISPATCH


def test_the_cap_defers_rather_than_drops(capsys, monkeypatch) -> None:
    """A capped sweep must not read as a clean one."""
    posts = []
    monkeypatch.setattr(sweeper, "_gh", _all_lost_transport(posts))
    sweeper.main(["--repo", "tuna-os/tunaOS"])
    out = capsys.readouterr().out
    assert "deferred 11" in out
    assert "deferred to the next sweep:" in out
    for name in sweeper.WORKFLOWS:
        assert name in out, f"{name} vanished from the report"


def test_the_common_case_is_still_immediate(monkeypatch) -> None:
    """One variant lost must recover on the very next sweep, not be rationed."""
    import json as _json

    posts = []

    def gh(args):
        joined = " ".join(args)
        if "--method" in args:
            posts.append(joined)
            return ""
        if "/runs?per_page" in joined:
            lost = "build-yellowfin" in joined
            return _json.dumps(
                [{
                    "id": 999 if lost else 1,
                    "event": "schedule",
                    "conclusion": "failure" if lost else "success",
                    "created_at": "2026-08-21T02:17:57Z",
                }]
            )
        if "/jobs?per_page" in joined:
            return "0\n" if "999" in joined else "30\n"
        return ""

    monkeypatch.setattr(sweeper, "_gh", gh)
    sweeper.main(["--repo", "tuna-os/tunaOS"])
    assert len(posts) == 1
    assert "build-yellowfin.yml" in posts[0]


def test_dry_run_dispatches_nothing(monkeypatch) -> None:
    posts = []
    monkeypatch.setattr(sweeper, "_gh", _all_lost_transport(posts))
    sweeper.main(["--repo", "tuna-os/tunaOS", "--dry-run"])
    assert posts == []


# --- failure handling -------------------------------------------------------


def test_gh_failures_carry_what_gh_said(monkeypatch) -> None:
    """The first live sweep's traceback said only "exited 1".

    capture_output swallowed the one line explaining why, which is the same
    defect as a capture step that tails past its own diagnostic.
    """
    import subprocess as _sp

    class Proc:
        returncode = 1
        stdout = ""
        stderr = "HTTP 403: Resource not accessible by integration"

    monkeypatch.setattr(_sp, "run", lambda *a, **k: Proc())
    with pytest.raises(sweeper.GhError) as excinfo:
        sweeper._gh(["api", "whatever"])
    assert "Resource not accessible" in str(excinfo.value)
    assert "exited 1" in str(excinfo.value)


def test_one_failed_dispatch_does_not_abandon_the_rest(capsys, monkeypatch) -> None:
    """The first live sweep aborted on its first POST.

    Every other lost variant went unrecovered -- the listing loop already
    kept going past one unreadable workflow, and the dispatch loop did not.
    """
    import json as _json

    posts = []

    def gh(args):
        joined = " ".join(args)
        if "--method" in args:
            posts.append(joined)
            if "build-albacore" in joined:
                raise sweeper.GhError("gh ... exited 1\n  stderr: HTTP 403")
            return ""
        if "/runs?per_page" in joined:
            return _json.dumps(
                [{"id": 999, "event": "schedule", "conclusion": "failure",
                  "created_at": "2026-08-21T02:17:57Z"}]
            )
        if "/jobs?per_page" in joined:
            return "0\n"
        return ""

    monkeypatch.setattr(sweeper, "_gh", gh)
    rc = sweeper.main(["--repo", "tuna-os/tunaOS"])
    out = capsys.readouterr().out

    # albacore is alphabetically first and fails. The sweep must carry on --
    # and the failure must not consume a cap slot, because it put nothing in
    # flight. So three POSTs are attempted and two succeed.
    assert len(posts) == 3, f"gave up after the first failure: {posts}"
    assert "re-dispatched 2" in out, "a failed dispatch ate a cap slot"
    assert "dispatch-failed 1" in out
    assert "dispatch FAILED: build-albacore.yml" in out
    assert "HTTP 403" in out, "the reason must reach the log"
    assert rc == 1, "a sweep that failed a dispatch must not read as green"


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
