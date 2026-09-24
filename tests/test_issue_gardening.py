"""Issue-gardening automation publishes maintainer readiness decisions.

Epic #2250 / #2261 asks the bot to add ``help wanted`` when a maintainer marks
an issue ready. tunaOS has two readiness labels, one for agents and one for
humans; both mean an unassigned issue is available to contributors. Keep the
repository wrapper small and the implementation in the org workflow.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "add-help-wanted.yml"
ORG_WORKFLOW = "tuna-os/.github/.github/workflows/reusable-add-help-wanted.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(document: dict) -> dict:
    # PyYAML 1.1 parses the unquoted Actions key ``on`` as True.
    return document.get("on", document.get(True, {}))


def test_only_a_label_event_can_offer_an_issue_for_contribution():
    assert _triggers(_load()) == {"issues": {"types": ["labeled"]}}


def test_both_ready_labels_invoke_the_shared_workflow():
    job = _load()["jobs"]["add-help-wanted"]
    condition = job["if"]
    assert "github.event.label.name == 'ready-for-agent'" in condition
    assert "github.event.label.name == 'ready-for-human'" in condition

    target = job["uses"]
    assert target.startswith(f"{ORG_WORKFLOW}@")
    revision = target.rsplit("@", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{40}", revision), (
        "org workflows are supply-chain inputs and must be commit-pinned"
    )


def test_the_caller_grants_only_the_permissions_the_shared_job_needs():
    assert _load()["permissions"] == {"contents": "read", "issues": "write"}
