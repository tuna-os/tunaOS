"""Contract tests for the scheduled dynamic half of fork safety (#2257)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "fork-simulation.yml"
SCRIPT = ROOT / "scripts" / "fork-simulation.py"
FIXTURE = ROOT / "scripts" / "fork-simulation-gh"

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
    assert "--env \"PATH=${act_homebrew_path}\"" in runner
    assert "fork-simulation-probe.sh" in runner
    assert "GITHUB_STEP_SUMMARY" in body
    assert "<!-- fork-simulation -->" in body
    assert "gh issue create" in body and "gh issue edit" in body
    assert "Fail when a simulation failed" in body
    assert "SIMULATION_UNEXPECTED_LOG" in runner
    assert "/run/fork-simulation-audit/api.log" in runner
    assert "/run/fork-simulation-audit/unexpected.log" in runner
    assert "audit_root" in runner
    assert ".fork-simulation-api.log" not in runner
    assert '--workflow "$workflow"' in runner

def test_act_homebrew_path_is_persisted_for_following_steps() -> None:
    action = (ROOT / ".github/actions/setup-tunaos/action.yml").read_text(encoding="utf-8")
    assert 'brew_bin="$(command -v brew || true)"' in action
    assert '/home/linuxbrew/.linuxbrew/bin/brew' in action
    assert '/root/.linuxbrew/bin/brew' in action
    assert 'brew_prefix="$("$brew_bin" --prefix)"' in action
    assert '"$GITHUB_PATH"' in action
    assert '"$GITHUB_ENV"' in action
    just_fix = (ROOT / ".github/workflows/just-fix.yml").read_text(encoding="utf-8")
    assert "- name: Persist Homebrew path" in just_fix
    assert 'brew_prefix="$("$brew_bin" --prefix)"' in just_fix
    assert '"$GITHUB_PATH"' in just_fix
    assert '"$GITHUB_ENV"' in just_fix



def run_fixture(
    tmp_path, persona, *arguments, token="fixture-token", stdin="", workflow="synthetic-workflow.yml"
):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            fork_simulation.event(
                persona, "tuna-os/tunaos", "head", "base", workflow
            )
        )
    )
    api_log = tmp_path / "api.log"
    unexpected_log = tmp_path / "unexpected.log"
    env = {
        **os.environ,
        "GITHUB_REPOSITORY": "tuna-os/tunaos",
        "SIMULATION_PR": "1",
        "GITHUB_EVENT_PATH": str(event_path),
        "SIMULATION_API_LOG": str(api_log),
        "SIMULATION_UNEXPECTED_LOG": str(unexpected_log),
    }
    env.pop("GITHUB_TOKEN", None)
    env["GH_TOKEN"] = token
    result = subprocess.run(
        [str(FIXTURE), "api", *arguments],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    calls = api_log.read_text().splitlines() if api_log.exists() else []
    unexpected = unexpected_log.read_text() if unexpected_log.exists() else ""
    return result, calls, unexpected


def test_same_repository_comment_delivery_is_exercised(tmp_path) -> None:
    body = tmp_path / "comment.md"
    body.write_text("synthetic reminder")
    result, calls, unexpected = run_fixture(
        tmp_path,
        "same-repo-contributor",
        "repos/tuna-os/tunaos/issues/1/comments",
        "-F",
        f"body=@{body}",
    )

    assert result.returncode == 0, result.stderr
    assert calls == ["POST\trepos/tuna-os/tunaos/issues/1/comments"]
    assert unexpected == ""

def test_fixture_reads_the_file_list_from_the_matching_synthetic_event(tmp_path) -> None:
    result, calls, unexpected = run_fixture(
        tmp_path,
        "same-repo-contributor",
        "repos/tuna-os/tunaos/pulls/1/files",
        workflow="pr-nudges.yml",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [".github/workflows/pr-nudges.yml"]
    assert calls == ["GET\trepos/tuna-os/tunaos/pulls/1/files"]
    assert unexpected == ""

def test_fixture_returns_empty_workflow_runs_for_matrix_structure_check(tmp_path) -> None:
    endpoint = (
        "repos/tuna-os/tunaos/actions/workflows/build-bonito.yml/runs"
        "?branch=main&per_page=1"
    )
    result, calls, unexpected = run_fixture(
        tmp_path,
        "same-repo-contributor",
        endpoint,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"workflow_runs": []}
    assert calls == [f"GET\t{endpoint}"]
    assert unexpected == ""


@pytest.mark.parametrize(
    ("persona", "token", "diagnostic"),
    [
        ("first-time-external", "read-only-token", "fork mutation"),
        ("same-repo-contributor", "", "unauthenticated mutation"),
    ],
)
def test_fixture_rejects_unauthorized_reviewer_mutation(
    tmp_path, persona, token, diagnostic
) -> None:
    result, calls, unexpected = run_fixture(
        tmp_path,
        persona,
        "-X",
        "DELETE",
        "repos/tuna-os/tunaos/pulls/1/requested_reviewers",
        "--input",
        "-",
        token=token,
        stdin="{}",
    )

    assert result.returncode != 0
    assert calls == ["DELETE\trepos/tuna-os/tunaos/pulls/1/requested_reviewers"]
    assert diagnostic in unexpected


def test_fixture_records_tolerated_unknown_calls_separately(tmp_path) -> None:
    result, calls, unexpected = run_fixture(
        tmp_path,
        "same-repo-contributor",
        "repos/tuna-os/tunaos/issues/1/unknown",
    )

    assert result.returncode != 0
    assert calls == ["GET\trepos/tuna-os/tunaos/issues/1/unknown"]
    assert "GET repos/tuna-os/tunaos/issues/1/unknown" in unexpected


def test_act_and_its_runner_image_are_immutable() -> None:
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "ACT_SHA256:" in body
    assert "sha256sum --check --strict" in body
    assert "ghcr.io/catthehacker/ubuntu:act-22.04@sha256:" in body
