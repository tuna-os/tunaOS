#!/usr/bin/env python3
"""Report Hacktoberfest external-contributor conversion from live GitHub data.

The Q4 target is merged pull requests from new contributors, not raw pull
request volume. This report excludes organization/repository insiders and bot
accounts, then checks whether each remaining author had a merged PR anywhere
in the tuna-os organization before the event window.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from collections.abc import Sequence
from typing import Any

ORG = "tuna-os"
DEFAULT_START = "2026-10-01"
DEFAULT_END = "2026-10-31"
DEFAULT_TARGET = 10
INTERNAL_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
# These authors account for most organization PR traffic. Excluding them in the
# server-side query keeps the result below GitHub Search's 1,000-result cap.
# The client-side checks below still reject all bots and internal associations.
QUERY_EXCLUSIONS = (
    "hanthor",
    "renovate[bot]",
    "dependabot[bot]",
    "github-actions[bot]",
    "hanthor-hive-agent[bot]",
)


def iso_date(value: str) -> str:
    """Return an ISO date or raise an argparse error."""
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value}") from exc
    return value


def positive_int(value: str) -> int:
    """Return a positive integer or raise an argparse error."""
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("target must be a positive integer") from exc
    if result < 1:
        raise argparse.ArgumentTypeError("target must be a positive integer")
    return result


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=iso_date, default=DEFAULT_START)
    parser.add_argument("--end", type=iso_date, default=DEFAULT_END)
    parser.add_argument("--target", type=positive_int, default=DEFAULT_TARGET)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if args.start > args.end:
        parser.error("--start must not be after --end")
    return args


def search(query: str, page: int = 1) -> dict[str, Any]:
    """Run one read-only GitHub issue-search request."""
    command = [
        "gh",
        "api",
        "-X",
        "GET",
        "search/issues",
        "-f",
        f"q={query}",
        "-f",
        "per_page=100",
        "-f",
        f"page={page}",
    ]
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True
        )
    except FileNotFoundError:
        raise RuntimeError("gh not found") from None
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "GitHub search failed"
        raise RuntimeError(detail) from None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse GitHub response: {exc}") from None


def is_external_human(item: dict[str, Any]) -> bool:
    """Identify authors eligible for the external-contributor metric."""
    user = item.get("user") or {}
    login = str(user.get("login") or "")
    association = str(item.get("author_association") or "").upper()
    return bool(
        login
        and user.get("type") != "Bot"
        and not login.lower().endswith("[bot]")
        and association not in INTERNAL_ASSOCIATIONS
    )


def repo_name(item: dict[str, Any]) -> str:
    return "/".join(str(item.get("repository_url") or "").split("/")[-2:])


def event_pull_requests(start: str, end: str) -> list[dict[str, Any]]:
    exclusions = " ".join(f"-author:{author}" for author in QUERY_EXCLUSIONS)
    query = (
        f"org:{ORG} is:pr is:merged archived:false "
        f"merged:{start}..{end} {exclusions}"
    )
    first = search(query)
    total = int(first.get("total_count", 0))
    if total > 1000:
        raise RuntimeError(
            "GitHub Search found more than 1,000 results after noise exclusions; "
            "refine QUERY_EXCLUSIONS before using this report"
        )

    items = list(first.get("items") or [])
    for page in range(2, (total + 99) // 100 + 1):
        items.extend(search(query, page).get("items") or [])
    return [item for item in items if is_external_human(item)]


def had_merged_pr_before(author: str, start: str) -> bool:
    query = (
        f"org:{ORG} is:pr is:merged archived:false author:{author} merged:<{start}"
    )
    return int(search(query).get("total_count", 0)) > 0


def build_report(start: str, end: str, target: int) -> dict[str, Any]:
    items = event_pull_requests(start, end)
    returning = {
        author
        for author in sorted({item["user"]["login"] for item in items})
        if had_merged_pr_before(author, start)
    }

    pull_requests = []
    for item in items:
        author = item["user"]["login"]
        pull_requests.append(
            {
                "repository": repo_name(item),
                "number": item.get("number"),
                "author": author,
                "status": "returning" if author in returning else "new",
                "merged_at": (item.get("pull_request") or {}).get("merged_at"),
                "url": item.get("html_url"),
                "title": item.get("title"),
            }
        )
    pull_requests.sort(
        key=lambda pr: (str(pr["merged_at"]), str(pr["repository"]), int(pr["number"]))
    )

    new_prs = [pr for pr in pull_requests if pr["status"] == "new"]
    returning_prs = [pr for pr in pull_requests if pr["status"] == "returning"]
    return {
        "organization": ORG,
        "start": start,
        "end": end,
        "target_new_contributor_merged_prs": target,
        "merged_prs_from_new_contributors": len(new_prs),
        "unique_new_contributors": len({pr["author"] for pr in new_prs}),
        "merged_prs_from_returning_external_contributors": len(returning_prs),
        "unique_returning_external_contributors": len(
            {pr["author"] for pr in returning_prs}
        ),
        "total_external_human_merged_prs": len(pull_requests),
        "pull_requests": pull_requests,
    }


def print_human(report: dict[str, Any]) -> None:
    print(
        f"Hacktoberfest conversion report: {report['start']} through {report['end']}"
    )
    print(
        "Merged PRs from new contributors: "
        f"{report['merged_prs_from_new_contributors']} / "
        f"{report['target_new_contributor_merged_prs']}"
    )
    print(f"Unique new contributors: {report['unique_new_contributors']}")
    print(
        "Merged PRs from returning external contributors: "
        f"{report['merged_prs_from_returning_external_contributors']}"
    )
    print(
        "Unique returning external contributors: "
        f"{report['unique_returning_external_contributors']}"
    )
    print(
        f"Total external-human merged PRs: "
        f"{report['total_external_human_merged_prs']}"
    )
    if report["pull_requests"]:
        print()
        print("status\tauthor\tpull request\tmerged")
        for pr in report["pull_requests"]:
            print(
                f"{pr['status']}\t{pr['author']}\t"
                f"{pr['repository']}#{pr['number']}\t{pr['merged_at']}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        report = build_report(args.start, args.end, args.target)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
