"""Strict native qualification is reachable only where it can say something true.

The strict plain+encrypted install gate fails its encrypted leg by policy until
the unmodified installed cold boot shows a passphrase prompt (#3380; run
40093907774 measured a black frame with one kernel line and no prompt on
serial or display). A check that runs on every PR, or every schedule, and
always reports the same failure cannot detect a regression: it is a dead gate
(AGENTS.md, "A permanently-red check is a dead gate").

So the wiring is pinned here:

- the strict job and the strict step are dispatch-only and native-artifact-only;
- every other trigger and source keeps the readiness smoke;
- no green criterion names the strict job or step as a gate, so the contract
  never promises a scheduled verdict that nothing produces;
- the verdict step runs even after a failed leg and reads the harness files.

Nothing here weakens or reorders a strict assertion.

Falsification: widening the qualify job to the pull_request trigger, running
the strict step for R2 media, naming the strict step in green-criteria.yml, or
dropping the always-run verdict step each fails one assertion below.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def steps(job: dict) -> dict[str, dict]:
    return {step["name"]: step for step in job["steps"] if "name" in step}


def normalized(expression: str) -> str:
    return " ".join(str(expression).split())


def test_the_qualify_job_is_dispatch_only_and_gnome_only():
    bootc = load("live-iso-bootc.yml")
    condition = normalized(bootc["jobs"]["qualify-native-iso"]["if"])
    assert "github.event_name == 'workflow_dispatch'" in condition
    # The evidence validator accepts flavor gnome only.
    assert "(github.event.inputs.flavor || 'gnome') == 'gnome'" in condition
    assert "pull_request" not in condition
    # The caller supplies no schedule of its own.
    assert "schedule" not in bootc.get(True, bootc.get("on", {}))


def test_the_only_caller_of_the_native_source_is_that_dispatch_job():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text())
        for name, job in (workflow.get("jobs") or {}).items():
            if job.get("uses") != "./.github/workflows/iso-e2e.yml":
                continue
            source = (job.get("with") or {}).get("source")
            assert source == "native-artifact", f"{path.name}:{name} calls iso-e2e.yml with source {source!r}"
            assert (path.name, name) == ("live-iso-bootc.yml", "qualify-native-iso")


def test_strict_runs_only_for_the_native_artifact_and_readiness_for_the_rest():
    e2e = steps(load("iso-e2e.yml")["jobs"]["e2e"])
    strict = e2e["Run strict offline GUI qualification"]
    readiness = e2e["Run readiness e2e"]
    assert "inputs.source == 'native-artifact'" in normalized(strict["if"])
    assert "inputs.source != 'native-artifact'" in normalized(readiness["if"])
    assert "--strict-offline-gui" in strict["run"]
    assert "--strict-offline-gui" not in readiness["run"]
    # Published and in-place media carry no embedded provenance; resolving it
    # for them would fail every readiness run on identity nothing promises.
    resolve = e2e["Resolve immutable ISO qualification inputs"]
    assert "inputs.source == 'native-artifact'" in normalized(resolve["if"])


def test_the_default_path_does_not_pay_the_strict_budget():
    job = load("iso-e2e.yml")["jobs"]["e2e"]
    timeout = normalized(job["timeout-minutes"])
    assert "inputs.source == 'native-artifact' && 160" in timeout
    assert timeout.endswith("&& 90 || 30) }}")


def test_the_verdict_step_runs_after_a_failed_leg():
    e2e = steps(load("iso-e2e.yml")["jobs"]["e2e"])
    verdict = e2e["Report strict leg verdicts"]
    condition = normalized(verdict["if"])
    assert condition.startswith("always()")
    assert "inputs.source == 'native-artifact'" in condition
    assert "summarize-strict-legs.py iso-e2e-out" in verdict["run"]
    assert "GITHUB_STEP_SUMMARY" in verdict["run"]
    names = list(e2e)
    assert names.index("Run strict offline GUI qualification") < names.index("Report strict leg verdicts")


def test_a_failed_strict_leg_still_fails_the_job():
    e2e = steps(load("iso-e2e.yml")["jobs"]["e2e"])
    strict = e2e["Run strict offline GUI qualification"]
    assert 'exit "$rc"' in strict["run"]
    assert "continue-on-error" not in strict
    validate = e2e["Validate strict qualification evidence"]
    assert "steps.strict.outputs.rc == '0'" in normalized(validate["if"])
    final = e2e["Fail on e2e error"]
    assert "steps.strict.outputs.rc || steps.e2e.outputs.rc" in normalized(final["if"])


def test_no_green_criterion_declares_the_strict_job_or_step():
    criteria = yaml.safe_load((ROOT / ".github/green-criteria.yml").read_text())
    declared = []
    for criterion in criteria["criteria"]:
        for gate in criterion.get("gates", []):
            declared.append(gate["workflow"])
            declared += list((gate.get("jobs") or {}).values())
            declared += gate.get("scripts", [])
    assert "Run strict offline GUI qualification" not in declared
    assert "qualify-native-iso" not in declared
    assert ".github/workflows/live-iso-bootc.yml" not in declared
    # The criterion that exists for ISOs keeps asserting the readiness smoke.
    iso = next(c for c in criteria["criteria"] if c["id"] == "iso")
    assert iso["gates"][0]["jobs"] == {"e2e": "Run readiness e2e"}
    assert "NOT a gate of this criterion" in iso["notes"]
