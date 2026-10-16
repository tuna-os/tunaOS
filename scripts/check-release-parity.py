#!/usr/bin/env python3
"""Did every tier-1 desktop stream ship the same daily release?

The flavor-equality mandate (#1315) makes GNOME, KDE, COSMIC, Niri and XFCE
equal release targets, and #1254 put all five in the scheduled matrix of
`.github/workflows/generate-changelog-release.yml`. Each matrix cell still
judges only itself, so one stream can drop a day while the run stays green.

That happened on 2026-10-02 (run 37034962525): gnome, kde and niri published
`<stream>-20261002`, while cosmic and xfce published nothing. Both cells read
an empty runs list from the API as "no build ran in the lookback window",
which the per-stream cadence gate treats as a legitimate no-op — the cosmic
release from the day before was less than a day old, so the age limit did
not fire either. The run concluded `success` (#2550).

This check looks across the streams instead of inside one. The newest
release date that ANY tier-1 stream reached is the bar: every other stream
must have a `<stream>-<that date>` release, and that release must carry the
assets users and the release card depend on. A day on which no stream
shipped passes, because nothing was skipped relative to anything else.

Usage:
  scripts/check-release-parity.py --releases FILE   # offline: `gh api .../releases` JSON
  scripts/check-release-parity.py --repo OWNER/NAME # query GitHub via `gh`
  ... [--streams gnome,kde,...] [--summary FILE]

Exit status: 0 when every stream is at parity, 1 when at least one lags or
is missing an asset, 2 when the releases could not be read.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field

# Keep in sync with the scheduled matrix in generate-changelog-release.yml;
# tests/test_release_parity.py fails when the two lists differ.
TIER1_STREAMS = ("gnome", "kde", "xfce", "cosmic", "niri")

# Every published release so far carries these two cards; the SBOM name is
# per-stream and checked separately below.
REQUIRED_ASSETS = ("release-card.png", "release-card-dark.png")

TAG_DATE = re.compile(r"^(?P<stream>.+)-(?P<date>\d{8})$")


@dataclass
class StreamVerdict:
    stream: str
    tag: str | None
    ok: bool
    problems: list[str] = field(default_factory=list)


def _sbom_present(stream: str, assets: list[str]) -> bool:
    # sbom-<variant>-<stream>-linux-amd64.spdx.json; the variant is a
    # dispatch input (yellowfin by default), so it is not pinned here.
    suffix = f"-{stream}-linux-amd64.spdx.json"
    return any(name.startswith("sbom-") and name.endswith(suffix) for name in assets)


def index_releases(releases: list[dict], streams: tuple[str, ...]) -> dict[str, dict[str, list[str]]]:
    """Map stream -> {YYYYMMDD: [asset names]} for published, non-draft releases.

    A tag is matched to a stream only when the whole prefix equals the stream
    name, so `kde-nvidia-20260705` is not counted as a `kde` release.
    """
    out: dict[str, dict[str, list[str]]] = {s: {} for s in streams}
    for rel in releases:
        if rel.get("draft"):
            continue
        m = TAG_DATE.match(rel.get("tag_name") or "")
        if not m or m.group("stream") not in out:
            continue
        assets = [a.get("name", "") for a in rel.get("assets") or []]
        out[m.group("stream")][m.group("date")] = assets
    return out


def evaluate(releases: list[dict], streams: tuple[str, ...] = TIER1_STREAMS) -> tuple[str | None, list[StreamVerdict]]:
    """Return (bar date, per-stream verdicts)."""
    index = index_releases(releases, streams)
    dates = [d for by_date in index.values() for d in by_date]
    if not dates:
        return None, [
            StreamVerdict(s, None, False, ["no published release for any tier-1 stream"])
            for s in streams
        ]
    bar = max(dates)

    verdicts = []
    for stream in streams:
        tag = f"{stream}-{bar}"
        assets = index[stream].get(bar)
        if assets is None:
            newest = max(index[stream], default=None)
            behind = f"newest is {stream}-{newest}" if newest else "no release at all"
            verdicts.append(StreamVerdict(stream, None, False, [f"missing {tag} ({behind})"]))
            continue
        problems = [f"{tag} lacks {name}" for name in REQUIRED_ASSETS if name not in assets]
        if not _sbom_present(stream, assets):
            problems.append(f"{tag} lacks an sbom-*-{stream}-linux-amd64.spdx.json asset")
        verdicts.append(StreamVerdict(stream, tag, not problems, problems))
    return bar, verdicts


def render(bar: str | None, verdicts: list[StreamVerdict]) -> str:
    lines = ["## Release parity — tier-1 desktop streams", ""]
    if bar is None:
        lines.append("❌ no tier-1 release found")
    else:
        lines.append(f"Bar: the newest release date any stream reached, `{bar}`.")
    lines += ["", "| Stream | Release | Result |", "|---|---|---|"]
    for v in verdicts:
        result = "✅" if v.ok else "❌ " + "; ".join(v.problems)
        lines.append(f"| {v.stream} | {v.tag or '—'} | {result} |")
    return "\n".join(lines) + "\n"


def fetch_releases(repo: str) -> list[dict]:
    # 100 releases is 20 days of five daily streams: far more history than
    # the bar date needs. A failed call raises; it must never read as "no
    # releases", which is the failure mode this check exists to catch.
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases?per_page=100"],
        check=True, capture_output=True, text=True,
    )
    return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--releases", help="JSON file in the shape of `gh api repos/O/R/releases`")
    src.add_argument("--repo", help="OWNER/NAME to query with `gh api`")
    ap.add_argument("--streams", default=",".join(TIER1_STREAMS),
                    help="comma-separated streams (default: %(default)s)")
    ap.add_argument("--summary", help="append the Markdown report to this file")
    args = ap.parse_args(argv)

    streams = tuple(s.strip() for s in args.streams.split(",") if s.strip())
    try:
        if args.releases:
            with open(args.releases, encoding="utf-8") as fh:
                releases = json.load(fh)
        else:
            releases = fetch_releases(args.repo)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        print(f"::error::could not read releases: {detail}", file=sys.stderr)
        return 2
    if not isinstance(releases, list):
        print("::error::releases payload is not a JSON list", file=sys.stderr)
        return 2

    bar, verdicts = evaluate(releases, streams)
    report = render(bar, verdicts)
    print(report, end="")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(report)

    failed = [v for v in verdicts if not v.ok]
    for v in failed:
        print(f"::error::release parity: {v.stream}: {'; '.join(v.problems)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
