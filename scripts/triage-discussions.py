#!/usr/bin/env python3
"""Select the oldest unanswered Q&A discussion for maintainer follow-up."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RESPONSE_TARGET_DAYS = 7
TRACKER_MARKER = re.compile(r"<!--\s*tunaos-discussion-response:(\d+)\s*-->")


def _created_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _candidate(discussion: Any) -> dict[str, Any] | None:
    if not isinstance(discussion, dict):
        return None

    category = discussion.get("category")
    if not isinstance(category, dict) or category.get("is_answerable") is not True:
        return None
    if discussion.get("answer_chosen_at"):
        return None

    number = discussion.get("number")
    title = discussion.get("title")
    url = discussion.get("html_url")
    created = _created_at(discussion.get("created_at"))
    if (
        type(number) is not int
        or number <= 0
        or not isinstance(title, str)
        or not title.strip()
        or not isinstance(url, str)
        or not url.startswith("https://github.com/")
        or created is None
    ):
        return None

    user = discussion.get("user")
    author = "unknown"
    if isinstance(user, dict) and isinstance(user.get("login"), str):
        author = _single_line(user["login"]) or "unknown"

    category_name = category.get("name")
    if not isinstance(category_name, str) or not category_name.strip():
        category_name = "Q&A"

    created_text = created.isoformat().replace("+00:00", "Z")
    due_text = (created + timedelta(days=RESPONSE_TARGET_DAYS)).isoformat().replace(
        "+00:00", "Z"
    )
    return {
        "number": number,
        "title": _single_line(title),
        "url": url,
        "author": author,
        "category": _single_line(category_name),
        "created_at": created_text,
        "due_at": due_text,
    }


def tracked_discussion_numbers(issues: list[Any]) -> set[int]:
    """Return discussion numbers already represented by any issue state."""
    tracked: set[int] = set()
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("pull_request") is not None:
            continue
        body = issue.get("body")
        if not isinstance(body, str):
            continue
        tracked.update(int(match) for match in TRACKER_MARKER.findall(body))
    return tracked


def unanswered_q_and_a(discussions: list[Any]) -> list[dict[str, Any]]:
    """Return valid unanswered Q&A discussions, oldest first."""
    candidates = [candidate for row in discussions if (candidate := _candidate(row))]
    return sorted(candidates, key=lambda row: (row["created_at"], row["number"]))


def _tracker(candidate: dict[str, Any]) -> dict[str, Any]:
    number = candidate["number"]
    marker = f"<!-- tunaos-discussion-response:{number} -->"
    title = candidate["title"]
    body_title = html.escape(title, quote=False)
    body_author = html.escape(candidate["author"], quote=False)
    body_category = html.escape(candidate["category"], quote=False)
    body_url = html.escape(candidate["url"], quote=True)
    body = f"""{marker}
## Discussion response needed

Please post a human response in [Discussion #{number}]({body_url}), then mark
its answer when it resolves the question.

- **Title:** {body_title}
- **Category:** {body_category}
- **Author:** @{body_author}
- **Created:** `{candidate['created_at']}`
- **Response target:** within {RESPONSE_TARGET_DAYS} days of creation (target:
  `{candidate['due_at']}`)

This issue is a queue signal, not a substitute for the public reply. The
workflow creates at most one tracker per run and never posts an answer or
closes issues; close this tracker manually after the discussion has a chosen
answer.
"""
    return {
        **candidate,
        "marker": marker,
        "issue_title": f"Discussion #{number} needs a response: {title}"[:256],
        "issue_body": body,
    }


def _load(path: Path) -> list[Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    raise ValueError("input must be a discussion object or a JSON array")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--existing-issues", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        discussions = unanswered_q_and_a(_load(args.input))
        issues = _load(args.existing_issues) if args.existing_issues else []
        tracked = tracked_discussion_numbers(issues)
        candidates = [row for row in discussions if row["number"] not in tracked]
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    result = _tracker(candidates[0]) if candidates else None
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
