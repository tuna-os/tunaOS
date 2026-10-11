"""Regression coverage for the org Renovate automerge boundary (#2833)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
CHECKER = ROOT / "scripts" / "check-renovate-automerge-policy.py"
WORKFLOW = ROOT / ".github" / "workflows" / "validate-renovate.yaml"


def run_checker(tmp_path: Path, config: dict) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "renovate.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return subprocess.run(
        ["python3", str(CHECKER), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_routine_updates_may_automerge(tmp_path: Path) -> None:
    result = run_checker(
        tmp_path,
        {
            "packageRules": [
                {
                    "matchUpdateTypes": ["minor", "patch", "pin", "digest"],
                    "automerge": True,
                }
            ]
        },
    )
    assert result.returncode == 0, result.stderr


def test_unscoped_major_automerge_is_rejected(tmp_path: Path) -> None:
    result = run_checker(tmp_path, {"automerge": True})
    assert result.returncode == 1
    assert "Major updates require human review" in result.stderr


def test_scoped_major_automerge_is_rejected(tmp_path: Path) -> None:
    result = run_checker(
        tmp_path,
        {
            "packageRules": [
                {
                    "matchPackageNames": ["example/package"],
                    "matchUpdateTypes": ["major"],
                    "automerge": True,
                }
            ]
        },
    )
    assert result.returncode == 1
    assert "scoped dependency set" in result.stderr


def test_later_unscoped_hold_cancels_a_broad_default(tmp_path: Path) -> None:
    result = run_checker(
        tmp_path,
        {
            "automerge": True,
            "packageRules": [
                {"matchUpdateTypes": ["major"], "automerge": False}
            ],
        },
    )
    assert result.returncode == 0, result.stderr


def test_workflow_validates_the_live_config_and_policy() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True]  # PyYAML 1.1 parses the unquoted YAML key `on` as True.
    watched_paths = set(triggers["pull_request"]["paths"])
    steps = workflow["jobs"]["validate"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)

    assert "renovate.json" in watched_paths
    assert str(CHECKER.relative_to(ROOT)) in watched_paths
    assert ".github/renovate.json5" not in watched_paths
    assert "renovate-config-validator --strict --no-global renovate.json" in commands
    assert "python3 scripts/check-renovate-automerge-policy.py renovate.json" in commands
