"""Contract tests for the scheduled dynamic half of fork safety (#2257)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "fork-simulation.yml"
SCRIPT = ROOT / "scripts" / "fork-simulation.py"

spec = importlib.util.spec_from_file_location("fork_simulation", SCRIPT)
fork_simulation = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fork_simulation)


def test_every_pull_request_workflow_has_a_reviewed_classification() -> None:
    discovered = set(fork_simulation.pull_request_workflows())
    simulated = set(fork_simulation.SIMULATED)
    excluded = set(fork_simulation.EXCLUDED)

    assert simulated.isdisjoint(excluded)
    assert discovered == simulated | excluded, (
        "every pull_request workflow must be dynamically simulated or carry "
        "an explicit reason why act cannot run it cheaply"
    )
    assert len(discovered) >= 10
    assert all(fork_simulation.EXCLUDED.values())


def test_the_fork_sensitive_write_lanes_are_in_dynamic_scope() -> None:
    assert set(fork_simulation.SIMULATED) == {
        "drop-bot-review-requests.yml",
        "just-fix.yml",
        "matrix-status.yml",
        "pr-nudges.yml",
    }


def test_matrix_runs_every_scoped_workflow_as_every_persona() -> None:
    expected = {
        (workflow, persona)
        for workflow in fork_simulation.SIMULATED
        for persona in fork_simulation.PERSONAS
    }
    actual = {(row["workflow"], row["persona"]) for row in fork_simulation.matrix()}
    assert actual == expected


def test_personas_have_realistic_trust_boundaries() -> None:
    external = fork_simulation.event(
        "first-time-external", "tuna-os/tunaos", "head", "base"
    )
    contributor = fork_simulation.event(
        "same-repo-contributor", "tuna-os/tunaos", "head", "base"
    )
    renovate = fork_simulation.event("renovate", "tuna-os/tunaos", "head", "base")

    assert external["pull_request"]["head"]["repo"]["fork"] is True
    assert external["pull_request"]["author_association"] == "FIRST_TIME_CONTRIBUTOR"
    assert contributor["pull_request"]["head"]["repo"]["full_name"] == "tuna-os/tunaos"
    assert contributor["pull_request"]["author_association"] == "MEMBER"
    assert renovate["sender"] == {"login": "renovate[bot]", "type": "Bot"}
    assert renovate["pull_request"]["user"]["type"] == "Bot"


def test_workflow_runs_real_steps_with_empty_secrets_and_reports_failures() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = fork_simulation.triggers(document)
    body = WORKFLOW.read_text(encoding="utf-8")

    assert "schedule" in triggers and "workflow_dispatch" in triggers
    runner = (ROOT / "scripts" / "run-fork-simulation.sh").read_text(encoding="utf-8")
    assert document["permissions"] == {}
    assert document["jobs"]["simulate-fork"]["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert document["jobs"]["simulate-internal"]["permissions"] == {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    }
    assert "act pull_request" in runner
    assert "--secret-file /dev/null" in runner
    assert '--secret "GITHUB_TOKEN=${SIMULATION_GITHUB_TOKEN}"' in runner
    assert '--actor "$(python3 scripts/fork-simulation.py actor "$persona")"' in runner
    assert "fork-simulation-probe.sh" in runner
    assert "GITHUB_STEP_SUMMARY" in body
    assert "<!-- fork-simulation -->" in body
    assert "gh issue create" in body and "gh issue edit" in body
    assert "Fail when a simulation failed" in body


def test_act_and_its_runner_image_are_immutable() -> None:
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "ACT_SHA256:" in body
    assert "sha256sum --check --strict" in body
    assert "ghcr.io/catthehacker/ubuntu:act-22.04@sha256:" in body
