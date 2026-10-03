#!/usr/bin/env python3
"""Collect the public, privacy-preserving TunaOS adoption signals.

The output is a point-in-time counter snapshot. GitHub release counters are
cumulative, so monthly download activity is the difference between consecutive
snapshots; they are not reconstructed from release publication dates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

REPO = "tuna-os/tunaOS"
API = "https://api.github.com"
ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "docs/adoption-metrics/snapshots"
REPORT = ROOT / "docs/adoption-metrics/README.md"
INTERNAL_ADOPTERS = ("@hanthor", "TunaOS Hive Agents")


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def previous_month(as_of: dt.date) -> tuple[dt.date, dt.date]:
    end = as_of.replace(day=1)
    start = (end - dt.timedelta(days=1)).replace(day=1)
    return start, end


class GitHub:
    def __init__(self, token: str | None):
        self.token = token

    def get(self, path: str) -> tuple[Any, dict[str, str]]:
        request = urllib.request.Request(f"{API}/{path.lstrip('/')}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response), dict(response.headers.items())
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"GitHub API {path} failed: {error.code} {detail}") from error

    def pages(self, path: str) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            payload, _ = self.get(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(payload, list):
                raise RuntimeError(f"GitHub API {path} did not return a list")
            items.extend(payload)
            if len(payload) < 100:
                return items
            page += 1

    def search_issues(self, query: str) -> list[dict[str, Any]]:
        encoded = urllib.parse.quote_plus(query)
        first, _ = self.get(f"search/issues?q={encoded}&per_page=100&page=1")
        total = int(first["total_count"])
        if total > 1000:
            raise RuntimeError(f"GitHub search for {query!r} has {total} results; split the window")
        items = list(first["items"])
        for page in range(2, (total + 99) // 100 + 1):
            payload, _ = self.get(f"search/issues?q={encoded}&per_page=100&page={page}")
            items.extend(payload["items"])
        return items


def is_bot(login: str, account_type: str | None = None) -> bool:
    lowered = login.lower()
    return account_type == "Bot" or lowered.endswith("[bot]") or "-bot" in lowered


def external_nonbot_prs(pulls: list[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    results = []
    for pull in pulls:
        merged = pull.get("merged_at") or (pull.get("pull_request") or {}).get("merged_at")
        user = pull.get("user") or {}
        login = user.get("login") or ""
        if not merged or not (start <= merged < end):
            continue
        if pull.get("author_association") in {"MEMBER", "OWNER"}:
            continue
        if not login or is_bot(login, user.get("type")):
            continue
        result = {"number": pull["number"], "author": login, "merged_at": merged}
        if pull.get("repository_url"):
            result["repository"] = pull["repository_url"].rsplit("/", 1)[-1]
        results.append(result)
    return sorted(results, key=lambda item: (item.get("repository", ""), item["number"]))


def merged_org_prs(github: GitHub, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    """Fetch org PRs in week-sized searches to stay below GitHub's 1,000-result cap."""
    results: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + dt.timedelta(days=7), end)
        inclusive_end = chunk_end - dt.timedelta(days=1)
        results.extend(
            github.search_issues(
                f"org:tuna-os is:pr is:merged merged:{cursor.isoformat()}..{inclusive_end.isoformat()}"
            )
        )
        cursor = chunk_end
    return results


def classify_release_assets(releases: list[dict[str, Any]]) -> dict[str, Any]:
    classes: dict[str, Counter[str]] = {
        "iso": Counter(),
        "sbom": Counter(),
        "release_card": Counter(),
        "other": Counter(),
    }
    for release in releases:
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            downloads = int(asset.get("download_count", 0))
            if name.lower().endswith(".iso"):
                kind = "iso"
            elif name.startswith("sbom-"):
                kind = "sbom"
            elif name.startswith("release-card"):
                kind = "release_card"
            else:
                kind = "other"
            classes[kind]["assets"] += 1
            classes[kind]["downloads"] += downloads
    return {
        kind: {"assets": values["assets"], "downloads": values["downloads"]}
        for kind, values in classes.items()
    }


def count_adopters(markdown: str) -> dict[str, int]:
    sections = {"production": "Production Users", "evaluation": "Development & Evaluation"}
    counts: dict[str, int] = {}
    for key, heading in sections.items():
        match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", markdown, re.M | re.S)
        body = match.group(1) if match else ""
        rows = [line for line in body.splitlines() if line.startswith("|")]
        entries = [line for line in rows if not re.match(r"^\|[- :|]+\|$", line) and "Organization" not in line]
        counts[key] = sum(not any(marker in row for marker in INTERNAL_ADOPTERS) for row in entries)
    counts["external_total"] = counts["production"] + counts["evaluation"]
    return counts


def collect(as_of: dt.date, github: GitHub) -> dict[str, Any]:
    start, end = previous_month(as_of)
    start_iso = f"{start.isoformat()}T00:00:00Z"
    end_iso = f"{end.isoformat()}T00:00:00Z"
    repository, headers = github.get(f"repos/{REPO}")
    releases = github.pages(f"repos/{REPO}/releases?")
    pulls = merged_org_prs(github, start, end)
    discussions = github.pages(f"repos/{REPO}/discussions?")
    external = external_nonbot_prs(pulls, start_iso, end_iso)
    discussion_rows = [
        {"number": row["number"], "created_at": row["created_at"]}
        for row in discussions
        if start_iso <= row["created_at"] < end_iso
    ]

    return {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "window": {"start": start.isoformat(), "end_exclusive": end.isoformat()},
        "sources": {
            "github": f"https://api.github.com/repos/{REPO}",
            "adopters": "ADOPTERS.md",
            "github_api_timestamp": headers.get("date") or headers.get("Date"),
        },
        "repository": {
            "stars": repository["stargazers_count"],
            "forks": repository["forks_count"],
            "watchers": repository["subscribers_count"],
        },
        "release_assets": {
            "release_count": len(releases),
            "classes": classify_release_assets(releases),
            "counter_semantics": "cumulative as of snapshot; subtract consecutive snapshots for interval activity",
        },
        "community": {
            "discussions_created": len(discussion_rows),
            "discussion_numbers": [row["number"] for row in discussion_rows],
            "external_nonbot_prs_merged": len(external),
            "external_nonbot_contributors": sorted({row["author"] for row in external}),
            "external_nonbot_prs": external,
        },
        "adopters": count_adopters((ROOT / "ADOPTERS.md").read_text()),
        "unavailable": {
            "r2_iso_downloads": "We have not connected an export from R2; the counters for release assets cannot replace it",
            "docs_visits": "We have not connected the Web Analytics export from Cloudflare",
            "installs": "No install telemetry by design; the consent decision remains open",
        },
    }


def render(snapshot: dict[str, Any]) -> str:
    repo = snapshot["repository"]
    assets = snapshot["release_assets"]["classes"]
    community = snapshot["community"]
    adopters = snapshot["adopters"]
    window = snapshot["window"]
    contributors = ", ".join(f"@{name}" for name in community["external_nonbot_contributors"]) or "none"
    return f"""# Adoption metrics snapshots

Latest snapshot: **{snapshot['as_of']}**. Activity covers `{window['start']}` through the day before `{window['end_exclusive']}`. Counter values are a point-in-time baseline.

| Signal | Value |
|---|---:|
| GitHub stars | {repo['stars']} |
| GitHub forks | {repo['forks']} |
| GitHub watchers | {repo['watchers']} |
| GitHub Release ISO assets / cumulative downloads | {assets['iso']['assets']} / {assets['iso']['downloads']} |
| GitHub Release SBOM assets / cumulative downloads | {assets['sbom']['assets']} / {assets['sbom']['downloads']} |
| Discussions opened in window | {community['discussions_created']} |
| External non-bot PRs merged across tuna-os in window | {community['external_nonbot_prs_merged']} |
| External non-bot contributors across tuna-os in window | {contributors} |
| External production/evaluation adopters | {adopters['external_total']} |

## Interpretation

GitHub Release counters are cumulative. Subtract the same counter in consecutive JSON snapshots to get activity between collection times. The release inventory now contains **{assets['iso']['assets']} ISO assets**; SBOM and release-card downloads do not count as ISO downloads or adoption. TunaOS stores its ISOs in R2. Variant and desktop rankings remain unavailable until the project connects an export from the access logs.

TunaOS collects no OS-level identifier or event. Stars, downloads, and site visits are discovery proxies, not proof of installation or continued use. GitHub marks accounts as `User` or `Bot`; a non-bot account is not proof that a human wrote its pull requests.

## Data gaps

- **R2 ISO downloads:** {snapshot['unavailable']['r2_iso_downloads']}.
- **Docs visits:** {snapshot['unavailable']['docs_visits']}.
- **Installs:** {snapshot['unavailable']['installs']}.

## Provenance

[`scripts/generate-adoption-snapshot.py`](../../scripts/generate-adoption-snapshot.py) generates the dated data in [`snapshots/`](snapshots/). The monthly workflow runs on the first day of each month and proposes the changed snapshot through a pull request.
"""


def write_snapshot(snapshot: dict[str, Any]) -> Path:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS / f"{snapshot['as_of']}.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(snapshot))
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=parse_date, default=dt.datetime.now(dt.UTC).date())
    args = parser.parse_args()
    snapshot = collect(args.date, GitHub(os.environ.get("GH_TOKEN")))
    path = write_snapshot(snapshot)
    print(f"wrote {path.relative_to(ROOT)} and {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
