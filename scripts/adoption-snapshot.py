#!/usr/bin/env python3
"""Collect public GitHub signals; fail rather than publish a partial baseline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from lib.gh import gh

ROOT = Path(__file__).resolve().parents[1]
REPO = "tuna-os/tunaos"


def api(endpoint: str, *, pages: bool = False):
    args = ["api", "--method", "GET", endpoint]
    if pages:
        args += ["--paginate", "--slurp"]
    data = json.loads(gh(args))
    return [item for page in data for item in page] if pages else data


def adopter_counts(text: str) -> dict:
    """Count listed entries, excluding dogfooding and the ecosystem table.

    ADOPTERS.md is the consent-reviewed source. This counts its entries, not
    verified installations. Keep internal identities explicit, not inferred
    from a contributor's account type or organization membership.
    """
    counts = {"production": 0, "evaluation": 0, "internal_excluded": 0}
    section = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = {
                "## Production Users": "production",
                "## Development & Evaluation": "evaluation",
            }.get(line)
        if section is None or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 4:
            raise ValueError("ADOPTERS.md entry must have four columns")
        if cells[0] == "Organization" or all(set(c) <= set("-: ") for c in cells):
            continue
        if "https://github.com/hanthor)" in cells[0] or "https://hive.tunaos.org)" in cells[0]:
            counts["internal_excluded"] += 1
        else:
            counts[section] += 1
    if "## Production Users" not in text or "## Development & Evaluation" not in text:
        raise ValueError("ADOPTERS.md sections changed; review the counter")
    return counts


def release_counts(releases: list) -> dict:
    iso_assets = []
    other_assets = 0
    other_downloads = 0
    published = [release for release in releases if not release["draft"]]
    for release in published:
        for asset in release["assets"]:
            if asset["name"].lower().endswith(".iso"):
                iso_assets.append({
                    "id": asset["id"], "name": asset["name"],
                    "url": asset["browser_download_url"],
                    "downloads": asset["download_count"],
                })
            else:
                other_assets += 1
                other_downloads += asset["download_count"]
    return {
        "published_releases": len(published),
        "iso_assets": sorted(iso_assets, key=lambda asset: asset["id"]),
        "iso_downloads_lifetime": sum(asset["downloads"] for asset in iso_assets),
        "non_iso_assets": other_assets,
        "non_iso_downloads_lifetime": other_downloads,
    }


def collect() -> dict:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    repo = api(f"repos/{REPO}")
    releases = api(f"repos/{REPO}/releases?per_page=100", pages=True)
    discussions = api(f"repos/{REPO}/discussions?per_page=100", pages=True)
    return {
        "schema_version": 1,
        "repository": REPO,
        "collection_started_at": started,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "sources": {
            "repository": f"https://api.github.com/repos/{REPO}",
            "releases": f"https://api.github.com/repos/{REPO}/releases?per_page=100",
            "discussions": f"https://api.github.com/repos/{REPO}/discussions?per_page=100",
            "adopters": "ADOPTERS.md at source_commit",
        },
        "discovery": {"stars": repo["stargazers_count"], "forks": repo["forks_count"]},
        "releases": release_counts(releases),
        "discussions": {
            "threads": len(discussions),
            "top_level_comments": sum(item["comments"] for item in discussions),
            "urls": sorted(item["html_url"] for item in discussions),
        },
        "external_adopter_entries": adopter_counts((ROOT / "ADOPTERS.md").read_text()),
        "unavailable": {
            "r2_iso_downloads": "No export of R2 access counts; ci-maintainer supplies it.",
            "iso_tracker_pageviews": "No export of Cloudflare pageviews; guide supplies it.",
            "external_human_contributions": "Needs a reviewed org-wide human/contributor census; strategist owns it.",
            "adoption_call_conversion": "Needs published Discussion URL and consent-confirmed follow-ups; see docs/ADOPTION-CALL.md.",
        },
    }


def render(data: dict) -> str:
    releases = data["releases"]
    adopters = data["external_adopter_entries"]
    rows = [
        ("GitHub stars / forks", f"{data['discovery']['stars']} / {data['discovery']['forks']}"),
        ("Published GitHub Releases", releases["published_releases"]),
        ("Retained GitHub ISO assets", len(releases["iso_assets"])),
        ("GitHub ISO downloads (lifetime)", releases["iso_downloads_lifetime"]),
        ("Other asset downloads (lifetime, excluded from ISO count)", releases["non_iso_downloads_lifetime"]),
        ("Discussion threads / top-level comments", f"{data['discussions']['threads']} / {data['discussions']['top_level_comments']}"),
        ("External production / evaluation entries", f"{adopters['production']} / {adopters['evaluation']}"),
        ("Internal adopter entries excluded", adopters["internal_excluded"]),
    ]
    lines = [
        f"# Adoption snapshot — {data['collected_at'][:10]}", "",
        f"Collected {data['collection_started_at']} to {data['collected_at']}.",
        f"Local evidence: `{data['source_commit']}`. Scope: `{data['repository']}`.", "",
        "| Signal | Value |", "|---|---:|",
        *[f"| {label} | {value} |" for label, value in rows], "",
        "Counters cover assets and threads that still exist at collection time.",
        "They are cumulative, not monthly downloads, unique users, or proof of installs.",
        "Deleted assets vanish from this inventory. ISO IDs and URLs are in the JSON.",
        "R2 downloads and browser-built ISOs are outside the GitHub counter.",
        "The count of comments excludes replies; threads include announcements and support.", "",
        "## Missing inputs", "",
        *[f"- `{key}`: unavailable — {reason}" for key, reason in data["unavailable"].items()], "",
        "## Roadmap decision", "",
        "Decisions to rank or retire variants need R2 downloads by variant and desktop.",
        "This snapshot cannot establish the Q4 adoption target or rank editions.",
        "The existing countme service reports each closed week in UTC; do not sum",
        "its weekly reports into unique monthly users. See services/countme/README.md.", "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    data = collect()  # No output is written if a required API request fails.
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = data["collected_at"][:10]
    (args.output_dir / f"{stem}.json").write_text(json.dumps(data, indent=2) + "\n")
    (args.output_dir / f"{stem}.md").write_text(render(data))


if __name__ == "__main__":
    main()
