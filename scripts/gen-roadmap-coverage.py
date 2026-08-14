#!/usr/bin/env python3
"""Regenerate the per-repo ROADMAP coverage block in ROADMAP.md.

Only the block between the GENERATED markers in the `### Community` section is
rewritten. Everything else in ROADMAP.md is hand-written strategy that no
generator should be touching.

Why this exists
---------------
Coverage was being counted by hand, and the hand-counts disagreed. Between
2026-08-10 and 2026-08-14, #1295 and #1361 recorded it as 5/38, 10/38, 13/42,
15/37, 9/42 and 16/39 — six numbers in five days, with four different
denominators. Almost none of that was repos actually gaining a ROADMAP; it was
disagreement about *which repos count* and *where the file has to live*.

So this script commits to both rules explicitly, and they are the whole point:

**Denominator** — every **non-archived, non-private** repo in the `tuna-os`
org. Forks count (four of the org's active repos are forks it develops in).
Archived repos do not, because a read-only repo cannot be planned; that is what
took `ubuntu` and `letters` out of scope on 2026-08-12, and it falls out of the
API rather than a hand-maintained exclusion list that would drift in its own
right.

**Numerator** — `ROADMAP.md` at the repo root **on the repo's default branch**.
Default branch, not `main`: `bootc-installer` develops on `dev` and
`changelog-action`, `kde-build-meta` and `mariner` on `master`. A checker that
hardcodes `main` reports those four as unplanned no matter what they contain,
which is exactly how `bootc-installer` came to be recorded as "ROADMAP stranded
on a non-default branch" (#1361) when the branch in question *is* its default.

Both rules are enforced here rather than described in prose, so the next
measurement is a command instead of an argument.

Usage:
    scripts/gen-roadmap-coverage.py [--check | --check-structure]
                                    [--repos-json PATH]

    --check            exit 1 if ROADMAP.md would change (byte-exact)
    --check-structure  exit 1 only on differences a pull request controls —
                       hand-edits inside the generated block — ignoring the
                       counts and repo lists, which are a function of live org
                       state
    --repos-json       read the repo inventory from a file instead of calling
                       the GitHub API. Each entry may carry a boolean
                       `hasRoadmap` to supply the probe result too, which is
                       what makes the unit tests runnable offline.

Note on CI: --check is deliberately NOT suitable as a pull_request gate. The
numbers here move when *another repo* gains a ROADMAP.md, so a byte-exact gate
would fail unrelated tunaOS PRs for something they neither caused nor can fix.
Gate on --check-structure (or run the generator on a schedule) instead; this is
the same split gen-matrix-status.py makes for the same reason.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

ORG = "tuna-os"
DOC = Path(__file__).resolve().parents[1] / "ROADMAP.md"
BEGIN = "<!-- BEGIN GENERATED — scripts/gen-roadmap-coverage.py -->"
END = "<!-- END GENERATED -->"

# Issues tracking the residual gap, cited in the generated block so a reader
# who spots an unplanned repo knows where the work is queued.
TRACKING = "#1295"


class ProbeError(RuntimeError):
    """A repo's ROADMAP could not be determined.

    Raised rather than defaulting the repo to "unplanned": a coverage number
    that silently counts an API failure as a missing roadmap reports a gap that
    may not exist, and reports it as confidently as a real one.
    """


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )


def fetch_repos() -> list[dict]:
    """The org's repo inventory, straight from the API."""
    proc = _gh([
        "repo", "list", ORG, "--limit", "200",
        "--json", "name,isArchived,isPrivate,defaultBranchRef",
    ])
    if proc.returncode != 0:
        raise ProbeError(f"gh repo list {ORG} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def active(repos: list[dict]) -> list[dict]:
    """The planning scope: non-archived, non-private. See module docstring."""
    scope = [r for r in repos if not r["isArchived"] and not r["isPrivate"]]
    return sorted(scope, key=lambda r: r["name"].lower())


def default_branch(repo: dict) -> str:
    ref = repo.get("defaultBranchRef") or {}
    branch = ref.get("name")
    if not branch:
        # An empty repo has no default branch, so it cannot carry a ROADMAP on
        # one. That is a real "unplanned", not a probe failure.
        return ""
    return branch


def has_roadmap(repo: dict) -> bool:
    """Does ROADMAP.md exist at this repo's root, on its default branch?"""
    if "hasRoadmap" in repo:  # supplied by --repos-json, for offline tests
        return bool(repo["hasRoadmap"])
    branch = default_branch(repo)
    if not branch:
        return False
    proc = _gh([
        "api", f"repos/{ORG}/{repo['name']}/contents/ROADMAP.md",
        "-X", "GET", "-f", f"ref={branch}", "-q", ".name",
    ])
    if proc.returncode == 0:
        return True
    # gh surfaces a genuine absence as a 404. Anything else — rate limit, auth,
    # a 5xx — is a failure to measure, and must not read as "no roadmap".
    if "404" in proc.stderr or "Not Found" in proc.stderr:
        return False
    raise ProbeError(
        f"could not probe {repo['name']}@{branch} for ROADMAP.md: "
        f"{proc.stderr.strip()}"
    )


def build(repos: list[dict], today: str | None = None) -> str:
    scope = active(repos)
    planned, unplanned, offbeat = [], [], []
    for repo in scope:
        name = repo["name"]
        branch = default_branch(repo)
        if has_roadmap(repo):
            planned.append(name)
            if branch not in ("main", ""):
                offbeat.append(f"`{name}` on `{branch}`")
        else:
            unplanned.append(name)

    total = len(scope)
    pct = round(100 * len(planned) / total) if total else 0
    stamp = today or datetime.date.today().isoformat()
    glyph = "✅" if not unplanned else "🟡"

    out = [
        BEGIN,
        "",
        f"- {glyph} **Per-repo ROADMAP coverage — {len(planned)} of {total} "
        f"active repos ({pct}%)**, measured {stamp} by "
        "[`scripts/gen-roadmap-coverage.py`](./scripts/gen-roadmap-coverage.py).",
        "  Scope is every non-archived, non-private repo in the `tuna-os` org; "
        "a repo counts as",
        "  planned when `ROADMAP.md` is at the root of its **default branch**. "
        "Archived repos are out",
        "  of scope because a read-only repo cannot be planned.",
    ]
    out += [
        "",
        f"  **Planned ({len(planned)})**: " + ", ".join(planned) + ".",
    ]
    if offbeat:
        out += [
            "",
            "  Counted on a non-`main` default branch: " + ", ".join(offbeat)
            + " — these are the repos' own default branches, not strandings.",
        ]
    if unplanned:
        out += [
            "",
            f"  **Unplanned ({len(unplanned)})**: " + ", ".join(unplanned)
            + f". Tracked by {TRACKING}.",
        ]
    out += ["", END]
    return "\n".join(out)


LIVE_COUNT = re.compile(r"\d+")


def structural(block: str) -> str:
    """The block with live org state masked out.

    Counts, percentages, the measurement date and the repo lists all move when
    another repo gains a ROADMAP — none of which a tunaOS pull request causes
    or can fix. What is left is the block's shape, which a hand-edit does break.
    """
    lines = []
    for line in block.splitlines():
        line = LIVE_COUNT.sub("N", line)
        # Repo-name runs are live state too; keep the label, drop the roster.
        line = re.sub(r"(\*\*(?:Planned|Unplanned) \(N\)\*\*: ).*", r"\1…", line)
        line = re.sub(r"(non-`main` default branch: ).*", r"\1…", line)
        lines.append(line)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="exit 1 if ROADMAP.md would change")
    mode.add_argument("--check-structure", action="store_true",
                      help="exit 1 only on differences a pull request controls "
                           "— hand-edits inside the generated block — ignoring "
                           "counts and rosters derived from live org state")
    ap.add_argument("--repos-json", type=Path,
                    help="read the repo inventory from a file instead of the "
                         "GitHub API")
    args = ap.parse_args()

    if not DOC.exists():
        sys.exit(f"{DOC} not found — run from the repo root")
    text = DOC.read_text()
    if BEGIN not in text or END not in text:
        sys.exit(f"{DOC} is missing the GENERATED markers")

    repos = (json.loads(args.repos_json.read_text()) if args.repos_json
             else fetch_repos())
    try:
        generated = build(repos)
    except ProbeError as exc:
        print(f"refusing to write a coverage number: {exc}", file=sys.stderr)
        return 2

    head, rest = text.split(BEGIN, 1)
    committed, tail = rest.split(END, 1)
    updated = head + generated + tail

    if args.check_structure:
        want = structural(BEGIN + committed + END)
        got = structural(generated)
        if want == got:
            print("ROADMAP.md coverage block structure is current "
                  "(live org state deliberately ignored)")
            return 0
        print(
            "ROADMAP.md's coverage block differs from the generator in content "
            "a pull request controls — the generated block was hand-edited. "
            "Run scripts/gen-roadmap-coverage.py and commit the result.",
            file=sys.stderr,
        )
        print("\n".join(difflib.unified_diff(
            want.splitlines(), got.splitlines(),
            fromfile="committed (live state masked)",
            tofile="generated (live state masked)",
            lineterm="",
        )), file=sys.stderr)
        return 1

    if updated == text:
        print("ROADMAP.md coverage block already current")
        return 0
    if args.check:
        print("ROADMAP.md coverage block is out of date", file=sys.stderr)
        return 1
    DOC.write_text(updated)
    print("ROADMAP.md coverage block regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
