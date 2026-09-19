"""Issue gardening stays advisory, fork-safe, and tied to lifecycle #2261."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _workflow(name: str) -> dict:
    return yaml.safe_load(_text(name))


def _triggers(doc: dict) -> dict:
    return doc.get("on", doc.get(True, {}))


def test_documented_lifecycle_labels_are_created_idempotently():
    text = _text("issue-labels.yml")
    for label in (
        "needs-triage", "needs-info", "needs-design", "ready-for-agent",
        "ready-for-human", "good first issue", "help wanted", "expert needed", "in progress",
        "blocked", "needs review", "inactive",
    ):
        assert f"['{label}'," in text
    assert "if (existing.has(name)) continue" in text
    assert "updateLabel" not in text


def test_inactivity_is_advisory_and_never_unassigns():
    text = _text("assignment-inactivity.yml")
    assert "14 * 24 * 60 * 60 * 1000" in text
    assert "cross-referenced" in text and "pull_request" in text
    assert "assignment-inactive:" in text
    assert "removeAssignees" not in text
    assert "nobody has been unassigned" in text


def test_greetings_handle_issues_and_fork_prs_without_checkout():
    doc = _workflow("greetings.yml")
    triggers = _triggers(doc)
    assert {"issues", "pull_request_target"} <= triggers.keys()
    assert "actions/checkout" not in _text("greetings.yml")
    assert "not a maintainer review" in _text("greetings.yml")


def test_regression_linker_only_reads_matching_merged_tests():
    text = _text("regression-test-links.yml")
    assert "github.event.pull_request.merged == true" in text
    assert "tests\\/regressions\\/test_issue_" in text
    assert "file.status !== 'removed'" in text
    assert "not a maintainer statement" in text


def test_weekly_report_surfaces_old_blocked_issues():
    text = _text("weekly-boot-report.yml")
    assert "date -u -d '30 days ago'" in text
    assert 'label:blocked updated:<${CUTOFF}' in text
    assert "Automated inventory only" in text
