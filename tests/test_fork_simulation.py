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


def test_matrix_discovers_every_pull_request_workflow() -> None:
    expected = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        document = yaml.safe_load(path.read_text()) or {}
        if "pull_request" in fork_simulation.triggers(document):
            expected.append(path.name)
    assert fork_simulation.pull_request_workflows() == expected
    assert len(expected) >= 5


def test_personas_have_realistic_trust_boundaries() -> None:
    external = fork_simulation.event("first-time-external", "tuna-os/tunaos", "head", "base")
    contributor = fork_simulation.event("same-repo-contributor", "tuna-os/tunaos", "head", "base")
    renovate = fork_simulation.event("renovate", "tuna-os/tunaos", "head", "base")

    assert external["pull_request"]["head"]["repo"]["fork"] is True
    assert external["pull_request"]["author_association"] == "FIRST_TIME_CONTRIBUTOR"
    assert contributor["pull_request"]["head"]["repo"]["full_name"] == "tuna-os/tunaos"
    assert contributor["pull_request"]["author_association"] == "MEMBER"
    assert renovate["sender"] == {"login": "renovate[bot]", "type": "Bot"}
    assert renovate["pull_request"]["user"]["type"] == "Bot"
    assert fork_simulation.PERSONAS["renovate"]["actor"] == "renovate[bot]"


def test_workflow_runs_weekly_without_secrets_and_reports_failures() -> None:
    document = yaml.safe_load(WORKFLOW.read_text())
    triggers = fork_simulation.triggers(document)
    body = WORKFLOW.read_text()

    assert "schedule" in triggers and "workflow_dispatch" in triggers
    assert "--secret-file /dev/null" in body
    assert '--actor "$(python3 scripts/fork-simulation.py actor "$persona")"' in body
    assert "--artifact-server-path" in body
    assert "contents: read" in body
    assert "GITHUB_STEP_SUMMARY" in body
    assert "first-time-external same-repo-contributor renovate" in body
    assert "<!-- fork-simulation -->" in body
    assert "gh issue create" in body and "gh issue edit" in body
    assert "Fail the run when a simulation failed" in body
