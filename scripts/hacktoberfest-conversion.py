#!/usr/bin/env python3
"""Read-only, paginated campaign PR evidence for tunaos#3148.

No account is classified as a new human without an operator-reviewed cohort.
API failures abort the receipt instead of turning missing data into zeroes.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys


DEFAULT_REPOS = (
    "tunaos", "docs", "tunaos-packages", "tromso", "xfce-linux", "tacklebox",
    "bootc-installer", "bootc-migrate",
)


def api(endpoint):
    result = subprocess.run(
        ["gh", "api", "--method", "GET", endpoint],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def in_window(value, start, end):
    return bool(value) and start <= timestamp(value) < end


def campaign_prs(repo, start, end):
    """Updated order lets us stop at a page wholly older than the window."""
    page = 1
    rows = {}
    while True:
        batch = api(
            f"repos/{repo}/pulls?state=all&sort=updated&direction=desc"
            f"&per_page=100&page={page}"
        )
        for pr in batch:
            if (in_window(pr["created_at"], start, end)
                    or in_window(pr["merged_at"], start, end)):
                rows[pr["number"]] = {"repository": repo, **pr}
        if not batch or all(timestamp(pr["updated_at"]) < start for pr in batch):
            return list(rows.values())
        page += 1


def load_cohort(path):
    """The ledger records review evidence; GitHub User type is not proof."""
    if path is None:
        return None
    entries = json.loads(path.read_text())
    if not isinstance(entries, list):
        raise ValueError("cohort must be an array of reviewed authors")
    cohort = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("cohort entries need login and evidence strings")
        login, evidence = entry.get("login"), entry.get("evidence")
        if (not isinstance(login, str) or not isinstance(evidence, str)
                or not login.strip() or not evidence.strip() or login.casefold() in cohort):
            raise ValueError("cohort needs unique logins and nonempty review evidence")
        cohort[login.casefold()] = {"login": login, "evidence": evidence}
    return cohort


def load_anchors(path):
    """Load prior campaign receipt to anchor first merges across windows."""
    if path is None:
        return {}
    data = json.loads(path.read_text())
    prs = data.get("pull_requests") if isinstance(data, dict) else data
    if not isinstance(prs, list):
        raise ValueError("anchors must be a receipt JSON with pull_requests or a list of PRs")
    anchors = {}
    for row in prs:
        if not isinstance(row, dict):
            continue
        author = row.get("author") or (row.get("user") or {}).get("login")
        merged_at = row.get("merged_at")
        if author and merged_at and row.get("reviewed_new_human", True):
            t = timestamp(merged_at)
            login = author.casefold()
            if login not in anchors or t < anchors[login]:
                anchors[login] = t
    return anchors


def summarize(prs, start, end, cohort, anchors=None):
    rows = []
    verified_merges = []
    anchor_merges = {}
    if anchors:
        if isinstance(anchors, dict) and "pull_requests" in anchors:
            anchors = anchors["pull_requests"]
        if isinstance(anchors, list):
            for row in anchors:
                if not isinstance(row, dict):
                    continue
                author = row.get("author") or (row.get("user") or {}).get("login")
                merged_at = row.get("merged_at")
                if author and merged_at and row.get("reviewed_new_human", True):
                    t = timestamp(merged_at)
                    login = author.casefold()
                    if login not in anchor_merges or t < anchor_merges[login]:
                        anchor_merges[login] = t
        elif isinstance(anchors, dict):
            for k, v in anchors.items():
                anchor_merges[k.casefold()] = v if isinstance(v, dt.datetime) else timestamp(v)

    for pr in sorted(prs, key=lambda item: item["html_url"]):
        author = pr.get("user") or {}
        login = author.get("login")
        reviewed = cohort is not None and login and login.casefold() in cohort
        verified = bool(reviewed and author.get("type") == "User")
        merged = in_window(pr["merged_at"], start, end)
        row = {
            "repository": pr["repository"], "url": pr["html_url"],
            "title": pr["title"], "author": login,
            "account_type": author.get("type"),
            "author_association": pr["author_association"],
            "created_at": pr["created_at"], "merged_at": pr["merged_at"],
            "opened_in_window": in_window(pr["created_at"], start, end),
            "merged_in_window": merged,
            "currently_open": pr["state"] == "open",
            "reviewed_new_human": verified,
        }
        rows.append(row)
        if verified and merged:
            verified_merges.append(row)

    metrics = None
    if cohort is not None:
        authors = {row["author"].casefold() for row in verified_merges}
        anchor_authors = {author for author in anchor_merges if author in cohort}
        all_authors = sorted(authors | anchor_authors)
        returning = []
        for author in all_authors:
            author_merges = [timestamp(row["merged_at"]) for row in verified_merges
                             if row["author"].casefold() == author]
            if author in anchor_merges:
                author_merges.append(anchor_merges[author])
            if not author_merges:
                continue
            first_merge = min(author_merges)
            followups = [row["url"] for row in rows
                         if row["reviewed_new_human"]
                         and row["author"].casefold() == author
                         and row["opened_in_window"]
                         and timestamp(row["created_at"]) > first_merge]
            if followups:
                returning.append({"login": cohort[author]["login"], "prs": followups})
        metrics = {
            "merged_prs": len(verified_merges),
            "unique_authors_with_merges": len(authors),
            "authors_with_followup_prs": returning,
            "merge_target": 10,
            "merge_target_met": len(verified_merges) >= 10,
        }
    return {
        "raw_activity": {
            "opened_prs": sum(row["opened_in_window"] for row in rows),
            "merged_prs": sum(row["merged_in_window"] for row in rows),
            "unique_merge_authors": len({row["author"].casefold() for row in rows
                                         if row["merged_in_window"] and row["author"]}),
        },
        "reviewed_cohort": None if cohort is None else list(cohort.values()),
        "new_human_conversion": metrics,
        "pull_requests": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", help="owner/name; repeat for scope")
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2026, 10, 1))
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 11, 1),
                        help="exclusive UTC date (default: 2026-11-01)")
    parser.add_argument("--cohort", type=Path, help="reviewed new-human JSON ledger")
    parser.add_argument("--anchors", type=Path, help="prior campaign receipt JSON to anchor first merges")
    args = parser.parse_args()
    if args.start >= args.end:
        parser.error("start must precede end")
    repos = sorted({repo.lower() for repo in (args.repo or [
        f"tuna-os/{name}" for name in DEFAULT_REPOS
    ])})
    if any(not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) for repo in repos):
        parser.error("repository must have the form owner/name")
    start = dt.datetime.combine(args.start, dt.time(), dt.timezone.utc)
    end = dt.datetime.combine(args.end, dt.time(), dt.timezone.utc)
    try:
        cohort = load_cohort(args.cohort)
        anchors = load_anchors(args.anchors)
        prs = [pr for repo in repos for pr in campaign_prs(repo, start, end)]
        report = summarize(prs, start, end, cohort, anchors=anchors)
        # Fetch diff totals only for reviewed conversions, not hundreds of bot PRs.
        additions = deletions = 0
        for row in report["pull_requests"]:
            if row["reviewed_new_human"] and row["merged_in_window"]:
                number = row["url"].rsplit("/", 1)[1]
                detail = api(f"repos/{row['repository']}/pulls/{number}")
                row["additions"], row["deletions"] = detail["additions"], detail["deletions"]
                additions += detail["additions"]
                deletions += detail["deletions"]
        if report["new_human_conversion"] is not None:
            report["new_human_conversion"].update(additions=additions, deletions=deletions)
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError, TypeError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        print(f"ERROR: incomplete campaign report: {detail.strip()}", file=sys.stderr)
        return 2
    print(json.dumps({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
        "repositories": repos, **report,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
