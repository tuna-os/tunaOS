"""Every workflow with a `schedule:` trigger is watched for failure.

A red scheduled run reports nowhere except the Actions tab. Before #3307, 46
of this repository's 47 cron workflows did exactly that: no tracking issue, no
notification, nothing an operator could see without opening the tab and
reading it. The weekly lifecycle sweep's 2026-08-13 failure sat unnoticed for
four days, which is the evidence `rerun-infra-failures.yml` already carries in
its own header.

`.github/workflows/scheduled-run-alert.yml` is the detector, and it matches
runs by workflow NAME through the `workflow_run.workflows` filter. That filter
is a transcribed list, and a transcribed list of 47 names has two failure modes
that produce no other symptom at all:

  * a new workflow lands with a `schedule:` and nobody adds it, so it is red
    and silent -- the original bug, recreated one workflow at a time;
  * an existing workflow's `name:` changes and the stale entry stops matching
    anything, so a workflow that *was* watched quietly stops being watched.

Both are invisible in CI and in review. This test is what makes them loud:
the watch list must equal the set of scheduled workflow names, exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
ALERT = WORKFLOW_DIR / "scheduled-run-alert.yml"


def _workflow_files() -> list[Path]:
    return sorted(
        [*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")],
        key=lambda p: p.name,
    )


def _triggers(doc: dict) -> dict:
    """The `on:` block. YAML 1.1 reads a bare `on` key as the boolean True."""
    on = doc.get("on", doc.get(True, {}))
    return on if isinstance(on, dict) else {}


def _scheduled() -> dict[str, str]:
    """`name:` -> file name, for every workflow that runs on cron."""
    found: dict[str, str] = {}
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text()) or {}
        if "schedule" not in _triggers(doc):
            continue
        found[doc["name"]] = path.name
    return found


def _watched() -> list[str]:
    doc = yaml.safe_load(ALERT.read_text()) or {}
    return list(_triggers(doc)["workflow_run"]["workflows"])


def _alert_job() -> dict:
    doc = yaml.safe_load(ALERT.read_text()) or {}
    (job,) = doc["jobs"].values()
    return job


def test_the_detector_exists() -> None:
    assert ALERT.is_file(), f"{ALERT.name} is the detector; nothing else files these issues."


def test_there_are_scheduled_workflows_to_watch() -> None:
    """Guard the guard: an empty scan would pass every assertion below."""
    assert len(_scheduled()) > 10


def test_every_scheduled_workflow_is_in_the_watch_list() -> None:
    missing = {
        name: file for name, file in _scheduled().items() if name not in set(_watched())
    }
    assert not missing, (
        "these workflows run on a schedule and nothing reports their failures; "
        f"add each `name:` to `on.workflow_run.workflows` in {ALERT.name}: "
        + ", ".join(f"{name!r} ({file})" for name, file in sorted(missing.items()))
    )


def test_no_watched_name_is_stale() -> None:
    """A renamed workflow leaves an entry that matches nothing, silently."""
    names = {doc["name"] for doc in (yaml.safe_load(p.read_text()) or {} for p in _workflow_files())}
    unknown = [name for name in _watched() if name not in names]
    assert not unknown, (
        f"{ALERT.name} watches names no workflow carries, so those runs are "
        f"unwatched: {unknown}. Match the current `name:` or drop the entry."
    )


def test_the_watch_list_has_no_duplicates() -> None:
    watched = _watched()
    assert len(watched) == len(set(watched)), "duplicate entries in the watch list"


def test_the_detector_does_not_watch_itself() -> None:
    """A listener that lists its own name re-triggers on its own completion."""
    doc = yaml.safe_load(ALERT.read_text()) or {}
    assert doc["name"] not in _watched()
    assert "schedule" not in _triggers(doc)


def test_the_detector_can_write_issues() -> None:
    """`issues: write` is the whole point; the default token cannot file one."""
    assert _alert_job()["permissions"]["issues"] == "write"
    # Listing the failed jobs for the issue body needs the runs API.
    assert _alert_job()["permissions"]["actions"] == "read"


def test_the_detector_acts_only_on_a_finished_scheduled_run() -> None:
    condition = " ".join(_alert_job()["if"].split())
    assert "github.event.workflow_run.event == 'schedule'" in condition, (
        "a workflow_dispatch or push leg is somebody watching their own run; "
        "only cron failures are unattended"
    )
    for conclusion in ("success", "failure", "timed_out"):
        assert conclusion in condition
    assert "cancelled" not in condition, (
        "a cancelled run is a concurrency group or a human, not an incident"
    )


def test_a_green_scheduled_run_closes_the_issue() -> None:
    """Without this the tracker fills with incidents that already recovered."""
    script = "".join(
        step.get("run", "") for step in _alert_job()["steps"]
    )
    assert "gh issue close" in script
    assert 'CONCLUSION" == "success"' in script


def test_the_serializing_group_is_on_the_job_and_not_the_workflow() -> None:
    """An ignored completion must not queue for the handler's one slot.

    The listener subscribes to every completion of 47 workflows, and the job's
    `if` drops most of them -- a `workflow_dispatch` leg, a cancelled run. A
    workflow-level `concurrency:` is entered before that `if` is evaluated, so
    those ignored runs would sit in the same group as the real handlers. A
    group holds one running and one pending entry, so an ignored completion
    taking the pending slot cancels the pending handler of a scheduled
    failure, and that eviction has no other symptom: no issue, no comment, no
    red job. A job that `if` skips never enters its group, so the group
    belongs on the job.
    """
    doc = yaml.safe_load(ALERT.read_text()) or {}
    assert "concurrency" not in doc, (
        "a workflow-level group admits the completions the job's `if` drops; "
        "they then compete for the handler's pending slot"
    )
    group = _alert_job()["concurrency"]
    assert group["cancel-in-progress"] is False, (
        "a cancelled handler is a dropped incident; the writes are serialized, "
        "not superseded"
    )
    assert "github.event.workflow_run.name" in group["group"], (
        "one tracking issue per watched workflow, so the group that serializes "
        "the read-modify-write is per watched workflow too"
    )
