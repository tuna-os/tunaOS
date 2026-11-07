"""Renovate churn is scheduled; security updates are not (CI cost, 2026-11).

Docker digest bumps were most of the week's Renovate merges, each one a full PR
pipeline run, a merge-queue run and a push run. The schedule coalesces them.
Falsification: removing a schedule, or scheduling vulnerability alerts, fails.
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS = json.loads((Path(__file__).parents[1] / "renovate.json").read_text(encoding="utf-8"))
RULES = SETTINGS["packageRules"]


def _rule(**match):
    found = [r for r in RULES if all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, match
    return found[0]


def test_docker_digest_bumps_run_once_a_day() -> None:
    rule = _rule(matchDatasources=["docker"], matchUpdateTypes=["digest"])
    assert rule["schedule"] == ["before 6am"]
    assert "automerge" not in rule, "the automerge decision lives in the blanket rule"


def test_workflow_and_npm_tooling_bumps_run_weekly() -> None:
    actions = next(r for r in RULES if "custom.regex" in r.get("matchManagers", []))
    assert actions["schedule"] == ["before 6am on monday"]
    assert actions["matchFileNames"] == [".github/workflows/**"]
    npm = _rule(matchDatasources=["npm"])
    assert npm["schedule"] == ["before 6am on monday"]
    assert npm["groupName"] == "npm tooling"


def test_the_docker_rule_comes_after_the_workflow_rule() -> None:
    """A docker image in a workflow file matches both; the later rule wins."""
    order = [i for i, r in enumerate(RULES) if "schedule" in r]
    names = [RULES[i].get("matchDatasources") or RULES[i].get("matchManagers") for i in order]
    assert names == [["github-actions", "custom.regex"], ["npm"], ["docker"]]


def test_pull_request_pressure_is_bounded() -> None:
    assert 1 <= SETTINGS["prConcurrentLimit"] <= 10
    assert 1 <= SETTINGS["prHourlyLimit"] <= 4


def test_security_updates_are_never_scheduled() -> None:
    alerts = SETTINGS["vulnerabilityAlerts"]
    assert alerts["schedule"] == ["at any time"]
