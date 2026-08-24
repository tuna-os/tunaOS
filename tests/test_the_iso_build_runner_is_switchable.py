"""Whether the ISO build actually needs AWS, made answerable.

installer-smoke.yml routes `build-iso` to RunsOn with this reason:

    RunsOn for all cells: the ISO build (tacklebox + podman) cannot work on
    the GitHub runner's podman 5.8.4 (tunaOS#1893).

Three steps later, in the same job, the podman setup step says:

    Both runner images ship podman 5.8.4 ... install the Kubic podman

Both runner images. The wedge is not a GitHub-runner property, and the fix is
a plain apt install with nothing runner-specific in it. tunaOS#1893's own root
cause turned out to be a `podman commit --quiet` wedge inside tacklebox, fixed
upstream in tacklebox#231 -- not a runner at all.

What genuinely differs is disk (80GB gp3 against ~14GB free of ~65GB) and
cores (8 against 4). Both are measurable, and neither has been measured. So
this adds a `build_runner` dispatch input rather than an opinion: same commit,
same steps, one flag.

These tests exist to stop the experiment from quietly becoming a change. The
default must stay RunsOn, and the weekly schedule -- which passes no inputs at
all -- must be untouchable from here.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = (Path(__file__).resolve().parents[1]
            / ".github" / "workflows" / "installer-smoke.yml")


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def build_job() -> dict:
    job = workflow()["jobs"]["build-iso"]
    assert job, "build-iso job not found; every assertion below is vacuous"
    return job


def test_the_input_exists_and_offers_both_runners():
    # `on` parses as the boolean True in YAML 1.1, which is why this is not
    # spelled wf["on"] -- a lookup that would KeyError and take the suite
    # with it.
    triggers = workflow()[True]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert "build_runner" in inputs, sorted(inputs)
    spec = inputs["build_runner"]
    assert spec["default"] == "runs-on", spec
    assert set(spec["options"]) == {"runs-on", "github"}, spec


def test_the_default_is_still_runs_on():
    """The experiment must not become the change by accident."""
    expr = str(build_job()["runs-on"])
    # The false branch of the ternary -- what an empty input falls through to.
    assert "runs-on={0}/runner={1}" in expr, expr
    assert "format(" in expr, expr


def test_asking_for_github_selects_a_github_runner():
    expr = str(build_job()["runs-on"])
    assert "inputs.build_runner == 'github'" in expr, expr
    # Order matters: the github branch must be the TRUE arm. Reversing them
    # would send every default run to ubuntu-latest, which is the mistake
    # this whole file is guarding.
    true_arm = expr.index("&&")
    false_arm = expr.index("||")
    assert true_arm < false_arm, expr
    assert "ubuntu-latest" in expr[true_arm:false_arm], expr
    assert "runs-on=" in expr[false_arm:], expr


def test_the_timeout_moves_with_the_runner():
    """Half the cores against a 75-minute cap would cancel the build and be
    read as "GitHub runners cannot do this" -- a timeout is not a
    measurement. The two must be driven by the same condition, or a later
    edit to one silently invalidates the experiment."""
    job = build_job()
    timeout = str(job["timeout-minutes"])
    assert "inputs.build_runner == 'github'" in timeout, timeout
    assert "75" in timeout, timeout
    minutes = [int(m) for m in re.findall(r"\b(\d{2,3})\b", timeout)]
    assert max(minutes) > 75, timeout


def test_the_weekly_schedule_cannot_be_switched_from_here():
    """`schedule` passes no inputs, so the expression evaluates empty and
    falls through to RunsOn. Asserted because the cost of being wrong is a
    weekly run silently changing platform with nobody watching."""
    triggers = workflow()[True]
    assert "schedule" in triggers, triggers
    sched = triggers["schedule"]
    assert isinstance(sched, list) and sched, sched
    for entry in sched:
        assert set(entry) == {"cron"}, entry


def test_the_podman_step_is_not_advertised_as_runs_on_only():
    """The step name said "on RunsOn" while its own comment said both images
    need it. A name that contradicts the body is how the RunsOn requirement
    went unexamined for as long as it did."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "setup working podman on RunsOn" not in text
    assert "name: setup working podman" in text

    steps = build_job()["steps"]
    names = [s.get("name", "") for s in steps]
    assert "setup working podman" in names, names
    # And it must still actually install the Kubic podman, or the experiment
    # tests a job that no longer does the thing under test.
    body = next(s for s in steps if s.get("name") == "setup working podman")
    assert "kubic" in body["run"].lower(), body["run"][:200]
