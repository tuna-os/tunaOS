"""A red scheduled run must open a tracking issue (#3307).

49 workflows run on a cron and 48 of them failed silently: nothing blocks on a
scheduled run, so the only way to learn one broke was to browse the Actions
tab. `scheduled-failure-alert.yml` is the one `workflow_run` listener for all
of them. These tests keep the list honest (a new scheduled workflow fails here
until it is listed), keep the listener unable to run repository code, and
execute its shell against a stubbed `gh` to prove it creates, comments and
closes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ALERT = WORKFLOWS / "scheduled-failure-alert.yml"

# Scheduled workflows that report their own failure.
SELF_REPORTING = {"daily-verify.yml": "files one issue per variant:flavor itself"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _triggers(doc: dict) -> dict:
    on = doc.get("on", doc.get(True, {}))
    return on if isinstance(on, dict) else {}


def _scheduled() -> dict[str, str]:
    return {
        f.name: _load(f)["name"]
        for f in sorted(WORKFLOWS.glob("*.y*ml"))
        if "schedule" in _triggers(_load(f)) and f.name not in SELF_REPORTING
    }


def test_every_scheduled_workflow_is_listed():
    listed = set(_triggers(_load(ALERT))["workflow_run"]["workflows"])
    expected = set(_scheduled().values())
    assert listed == expected, (
        f"unlisted: {sorted(expected - listed)}; stale: {sorted(listed - expected)}. "
        "Edit the `workflows:` list in scheduled-failure-alert.yml."
    )


def test_the_listener_never_runs_repository_code():
    doc = _load(ALERT)
    assert doc["permissions"] == {}
    job = doc["jobs"]["alert"]
    assert job["permissions"] == {"actions": "read", "issues": "write"}
    assert not any("uses" in step for step in job["steps"]), (
        "a workflow_run job holds a write token; it must not check out or run actions"
    )
    for step in job["steps"]:
        assert "${{" not in step.get("run", ""), (
            "event data must reach the script through env:, not interpolation"
        )


def test_only_scheduled_failures_and_recoveries_are_handled():
    cond = _load(ALERT)["jobs"]["alert"]["if"]
    assert "workflow_run.event == 'schedule'" in cond
    assert "conclusion == 'failure'" in cond and "conclusion == 'success'" in cond
    assert "cancelled" not in cond


@pytest.mark.skipif(not shutil.which("jq"), reason="jq not installed")
class TestAlertScript:
    @staticmethod
    def _script() -> str:
        return _load(ALERT)["jobs"]["alert"]["steps"][0]["run"]

    def _run(self, tmp_path, conclusion: str, open_issues: list[dict]):
        stub = tmp_path / "bin"
        stub.mkdir()
        log = tmp_path / "gh.log"
        issues = tmp_path / "issues.json"
        issues.write_text(json.dumps(open_issues))
        jobs = tmp_path / "jobs.json"
        jobs.write_text(json.dumps({"jobs": [
            {"name": "build / gnome", "conclusion": "failure"},
            {"name": "lint", "conclusion": "success"},
        ]}))
        gh = stub / "gh"
        gh.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s" "$*" | tr "\\n" "|" >> {log}; echo >> {log}\n'
            'case "$1 $2" in\n'
            f'  "issue list") cat {issues} ;;\n'
            f'  "run view") cat {jobs} ;;\n'
            "esac\n"
        )
        gh.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{stub}:{os.environ['PATH']}",
            "WORKFLOW_NAME": "Check base image pins",
            "WORKFLOW_PATH": ".github/workflows/check-base-image-pins.yml",
            "CONCLUSION": conclusion,
            "RUN_ID": "42",
            "RUN_URL": "https://example.test/runs/42",
            "RUN_ATTEMPT": "1",
            "HEAD_SHA": "a" * 40,
        }
        result = subprocess.run(
            ["bash", "-c", self._script()], env=env, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stderr
        return log.read_text().splitlines() if log.exists() else []

    TITLE = "[ci] Check base image pins scheduled run failed"

    def test_failure_with_no_open_issue_creates_one(self, tmp_path):
        calls = self._run(tmp_path, "failure", [])
        create = [c for c in calls if c.startswith("issue create")]
        assert len(create) == 1
        assert self.TITLE in create[0] and "--label ci-failure" in create[0]
        assert "- build / gnome" in create[0] and "- lint" not in create[0]

    def test_repeat_failure_comments_on_the_open_issue(self, tmp_path):
        calls = self._run(tmp_path, "failure", [{"number": 7, "title": self.TITLE}])
        assert not any(c.startswith("issue create") for c in calls)
        assert any(c.startswith("issue comment 7 ") for c in calls)

    def test_a_similar_title_is_not_the_same_issue(self, tmp_path):
        calls = self._run(tmp_path, "failure", [{"number": 9, "title": self.TITLE + " twice"}])
        assert any(c.startswith("issue create") for c in calls)

    def test_success_closes_the_open_issue(self, tmp_path):
        calls = self._run(tmp_path, "success", [{"number": 7, "title": self.TITLE}])
        assert any(c.startswith("issue close 7 ") for c in calls)
        assert not any(c.startswith("issue create") for c in calls)

    def test_success_with_no_open_issue_does_nothing(self, tmp_path):
        calls = self._run(tmp_path, "success", [])
        assert not any(c.startswith(("issue create", "issue close", "issue comment")) for c in calls)
