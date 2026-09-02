"""Whether the ISO build needs AWS — measured, then acted on.

installer-smoke.yml routed `build-iso` to RunsOn with this reason:

    RunsOn for all cells: the ISO build (tacklebox + podman) cannot work on
    the GitHub runner's podman 5.8.4 (tunaOS#1893).

Three steps later, in the same job, the podman setup step said "both runner
images ship podman 5.8.4 ... install the Kubic podman". The wedge was never a
GitHub-runner property, and tunaOS#1893's root cause turned out to be a
`podman commit --quiet` wedge inside tacklebox, fixed in tacklebox#231.

What was genuinely unknown was disk and cores. Run 32747410944 settled both,
same commit and same steps as the RunsOn runs it is compared against:

    Build dev ISO      ubuntu-latest      RunsOn (c6a, 8 vCPU)
    gnome              38m46s             48m18s
    kde                41m16s             59m53s

Faster on both flavors with half the cores, no disk failure, and the gnome
leg green end to end including the walkthrough. So ubuntu-latest is the
default and RunsOn is the escape hatch.

These tests hold the switch honest in the new direction: the default really
is the GitHub runner, `build_runner: runs-on` really does route back, and the
two cannot drift apart.
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


GUARD = "inputs.build_runner != 'runs-on'"


def test_the_input_exists_and_offers_both_runners():
    # `on` parses as the boolean True in YAML 1.1, which is why this is not
    # spelled wf["on"] -- a lookup that would KeyError and take the suite
    # with it.
    triggers = workflow()[True]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert "build_runner" in inputs, sorted(inputs)
    spec = inputs["build_runner"]
    assert spec["default"] == "github", spec
    assert set(spec["options"]) == {"runs-on", "github"}, spec


def test_the_default_is_the_github_runner():
    expr = str(build_job()["runs-on"])
    # The guard is written as != 'runs-on' rather than == 'github' on
    # purpose: `schedule` passes no inputs at all, so an == comparison would
    # send the weekly run down the RunsOn path while every dispatch went to
    # ubuntu-latest. One default, both triggers.
    assert GUARD in expr, expr
    true_arm = expr.index("&&")
    false_arm = expr.index("||")
    assert true_arm < false_arm, expr
    assert "ubuntu-latest" in expr[true_arm:false_arm], expr


def test_asking_for_runs_on_routes_back_to_aws():
    """The escape hatch has to survive, or reverting needs a code change."""
    expr = str(build_job()["runs-on"])
    false_arm = expr.index("||")
    assert "runs-on={0}/runner={1}" in expr[false_arm:], expr
    assert "format(" in expr[false_arm:], expr


def test_the_timeout_moves_with_the_runner():
    """A cap close to the observed build time turns a slow build into a
    cancellation and reports the wrong thing. The two must be driven by the
    same condition, or a later edit to one silently invalidates the other."""
    timeout = str(build_job()["timeout-minutes"])
    assert GUARD in timeout, timeout
    assert "75" in timeout, timeout
    minutes = [int(m) for m in re.findall(r"\b(\d{2,3})\b", timeout)]
    # Measured builds are 38-41 minutes; the cap must leave real headroom.
    assert max(minutes) >= 120, timeout


def test_the_weekly_schedule_takes_the_same_default():
    """`schedule` passes no inputs, so `inputs.build_runner` is empty.

    Under the != comparison that lands on ubuntu-latest, which is the
    intended behaviour now -- one default for both triggers. Asserted
    because switching it back to == would silently split them, and the
    weekly run is the one nobody watches.
    """
    triggers = workflow()[True]
    assert "schedule" in triggers, triggers
    sched = triggers["schedule"]
    assert isinstance(sched, list) and sched, sched
    for entry in sched:
        assert set(entry) == {"cron"}, entry
    expr = str(build_job()["runs-on"])
    assert "== 'github'" not in expr, (
        "an == comparison sends the scheduled run to RunsOn while every "
        "dispatch goes to ubuntu-latest; use != 'runs-on' so both triggers "
        "share one default"
    )


def test_the_measurement_is_recorded_next_to_the_switch():
    """The numbers are the entire argument for the default.

    Without them the next reader sees an unexplained platform choice and the
    old "RunsOn is required" comment reads as still true."""
    body = WORKFLOW.read_text(encoding="utf-8")
    for token in ("38m46s", "48m18s", "32747410944"):
        assert token in body, f"{token} missing from the workflow rationale"


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


# ── live-iso-bootc.yml ───────────────────────────────────────────────────
# The same switch, deliberately wired the OTHER way round. Two workflows with
# opposite comparisons is exactly the kind of asymmetry that gets "tidied" into
# a bug, so it is pinned here with the reason attached.

LIVE_ISO = (Path(__file__).resolve().parents[1]
            / ".github" / "workflows" / "live-iso-bootc.yml")


def live_iso_build_job() -> dict:
    wf = yaml.safe_load(LIVE_ISO.read_text(encoding="utf-8"))
    job = wf["jobs"]["build"]
    assert job, "live-iso build job not found; the assertions below are vacuous"
    return job


def test_the_live_iso_build_can_opt_in_to_a_github_runner():
    wf = yaml.safe_load(LIVE_ISO.read_text(encoding="utf-8"))
    spec = wf[True]["workflow_dispatch"]["inputs"]["build_runner"]
    assert set(spec["options"]) == {"runs-on", "github"}, spec


def test_the_live_iso_build_defaults_to_github_hosted():
    """GitHub-hosted is the default; RunsOn is the opt-out.

    This asserted the opposite until 2026-08-25, on the grounds that the
    installer-smoke measurement was about a different shape of work and
    this job had never been timed on ubuntu-latest. Two things changed.

    The measurement arrived from iso-e2e.yml: the same tacklebox
    customize-and-commit completes in 133s on ubuntu-latest and the cell
    boots (skipjack:kde, job 97648442043) once the build runs in one root
    context instead of being handed through rootless storage. This job now
    does exactly that.

    And the cost of the old default became visible: RunsOn is billed EC2,
    the PR trigger fires on the PR's whole diff rather than the pushed
    commit, and a day of pushes to one branch put spend at $9.87 against a
    $5.00 budget. GitHub-hosted runners are included, with 60 concurrent
    jobs.
    """
    wf = yaml.safe_load(LIVE_ISO.read_text(encoding="utf-8"))
    spec = wf[True]["workflow_dispatch"]["inputs"]["build_runner"]
    assert spec["default"] == "github", spec
    assert set(spec["options"]) == {"github", "runs-on"}, spec


def test_an_input_less_trigger_gets_the_github_default():
    """The comparison has to be `!= 'runs-on'`, and this pins WHY.

    `pull_request` and `schedule` pass no inputs, so the expression sees an
    empty string. Under `== 'github'` that is false and every input-less
    run lands on RunsOn — which is precisely how the PR trigger came to
    bill an EC2 ISO build on every push. Under `!= 'runs-on'` it is true
    and they get the default.

    Resolved rather than string-matched: an expression can read correctly
    and evaluate the wrong way.
    """
    wf = yaml.safe_load(LIVE_ISO.read_text(encoding="utf-8"))
    assert "pull_request" in wf[True], sorted(wf[True])
    expr = " ".join(str(live_iso_build_job()["runs-on"]).split())

    def resolve(build_runner):
        m = re.search(
            r"\$\{\{ inputs\.build_runner (!=|==) '([\w-]+)' "
            r"&& '([^']+)' \|\| (.+?) \}\}$",
            expr,
        )
        assert m, f"unrecognised runs-on expression: {expr!r}"
        op, operand, true_arm, false_arm = m.groups()
        hit = (build_runner != operand) if op == "!=" else (build_runner == operand)
        return true_arm if hit else false_arm.strip()

    assert resolve("") == "ubuntu-latest", (
        "an input-less trigger (pull_request, schedule) does not get the "
        "GitHub-hosted default — this is the case that was billing EC2"
    )
    assert resolve("github") == "ubuntu-latest", "explicit github must be GitHub-hosted"
    assert "runner=build-amd64" in resolve("runs-on"), "the opt-out must still reach RunsOn"
