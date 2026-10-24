"""Unanswered Q&A discussions must become a bounded maintainer queue."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "triage-discussions.py"
WORKFLOW = ROOT / ".github" / "workflows" / "discussion-triage.yml"

_spec = importlib.util.spec_from_file_location("triage_discussions", SCRIPT)
assert _spec and _spec.loader
triage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(triage)


def _discussion(
    number: int,
    created_at: str,
    *,
    answerable: bool = True,
    answered_at: str | None = None,
    title: str = "Can I run this?",
    author: str = "visitor",
) -> dict:
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/orgs/tuna-os/discussions/{number}",
        "created_at": created_at,
        "answer_chosen_at": answered_at,
        "category": {"name": "Q&A", "is_answerable": answerable},
        "user": {"login": author},
    }


def _triggers(document: dict) -> dict:
    # PyYAML 1.1 parses the unquoted Actions key ``on`` as True.
    return document.get("on", document.get(True, {}))


def test_oldest_unanswered_q_and_a_is_selected_first() -> None:
    rows = [
        _discussion(93, "2026-04-20T20:10:39Z", title="Will this run on ARM?"),
        _discussion(12, "2026-04-19T20:10:39Z", title="Older question"),
        _discussion(
            8,
            "2026-04-18T20:10:39Z",
            answered_at="2026-04-19T20:10:39Z",
        ),
        _discussion(4, "2026-04-17T20:10:39Z", answerable=False),
    ]

    selected = triage.unanswered_q_and_a(rows)

    assert [row["number"] for row in selected] == [12, 93]
    assert selected[0]["due_at"] == "2026-04-26T20:10:39Z"


def test_tracker_body_is_a_public_reply_instruction_not_an_automated_answer() -> None:
    candidate = triage.unanswered_q_and_a(
        [_discussion(93, "2026-04-20T20:10:39Z", title="Use <x> & `y`?")]
    )[0]

    tracker = triage._tracker(candidate)

    assert tracker["marker"] == "<!-- tunaos-discussion-response:93 -->"
    assert tracker["issue_title"] == "Discussion #93 needs a response: Use <x> & `y`?"
    assert "Discussion #93" in tracker["issue_body"]
    assert "Use &lt;x&gt; &amp; `y`?" in tracker["issue_body"]
    assert "never posts an answer or" in tracker["issue_body"]
    assert "closes issues" in tracker["issue_body"]


def test_existing_trackers_are_skipped_across_successive_sweeps(tmp_path: Path) -> None:
    discussions_path = tmp_path / "discussions.json"
    issues_path = tmp_path / "issues.json"
    output_path = tmp_path / "candidate.json"
    discussions_path.write_text(
        json.dumps(
            [
                _discussion(12, "2026-04-18T20:10:39Z", title="Already queued"),
                _discussion(93, "2026-04-19T20:10:39Z", title="Next question"),
            ]
        ),
        encoding="utf-8",
    )
    issues_path.write_text(
        json.dumps(
            [
                {
                    "number": 501,
                    "state": "closed",
                    "body": "<!-- tunaos-discussion-response:12 -->",
                }
            ]
        ),
        encoding="utf-8",
    )

    assert triage.main(
        [
            "--input",
            str(discussions_path),
            "--existing-issues",
            str(issues_path),
            "--output",
            str(output_path),
        ]
    ) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["number"] == 93


def test_issue_title_is_capped_but_body_keeps_full_discussion_title() -> None:
    title = "x" * 300
    candidate = triage.unanswered_q_and_a(
        [_discussion(93, "2026-04-20T20:10:39Z", title=title)]
    )[0]

    tracker = triage._tracker(candidate)

    assert len(tracker["issue_title"]) == 256
    assert tracker["issue_title"].startswith("Discussion #93 needs a response: ")
    assert title in tracker["issue_body"]


def test_malformed_rows_are_ignored_without_hiding_valid_questions() -> None:
    rows = [
        None,
        {"number": 1, "category": {"is_answerable": True}},
        _discussion(2, "2026-04-20T20:10:39Z"),
    ]

    assert [row["number"] for row in triage.unanswered_q_and_a(rows)] == [2]


def test_cli_emits_null_when_no_unanswered_q_and_a(tmp_path: Path) -> None:
    input_path = tmp_path / "discussions.json"
    output_path = tmp_path / "candidate.json"
    input_path.write_text(
        json.dumps([_discussion(1, "2026-04-20T20:10:39Z", answered_at="2026-04-21T00:00:00Z")]),
        encoding="utf-8",
    )

    assert triage.main(["--input", str(input_path), "--output", str(output_path)]) == 0
    assert json.loads(output_path.read_text(encoding="utf-8")) is None


def test_workflow_sweeps_and_supports_a_manual_backfill() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = _triggers(document)

    assert triggers["discussion"] == {"types": ["created"]}
    assert triggers["schedule"] == [{"cron": "17 9 * * *"}]
    assert "discussion_number" in triggers["workflow_dispatch"]["inputs"]
    assert document["permissions"] == {
        "contents": "read",
        "discussions": "read",
        "issues": "write",
    }

    run_blocks = [
        step["run"]
        for step in document["jobs"]["triage"]["steps"]
        if "run" in step
    ]
    run_text = "\n".join(run_blocks)
    assert "gh issue create" in run_text
    assert "gh issue list" not in run_text
    assert "issues?state=all&per_page=100" in run_text
    assert "--existing-issues issues.json" in run_text
    assert "gh issue close" not in run_text
    assert "github.event.discussion.title" not in run_text
    assert "github.event.discussion.body" not in run_text


def test_checkout_action_is_commit_pinned() -> None:
    checkout = next(
        step["uses"]
        for step in yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["triage"]["steps"]
        if step.get("name") == "Checkout selector"
    )
    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", checkout)
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1" in WORKFLOW.read_text(encoding="utf-8")
