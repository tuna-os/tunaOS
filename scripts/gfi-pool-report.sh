#!/usr/bin/env bash
# gfi-pool-report.sh — what a first-time contributor can actually pick up today.
#
# docs/HACKTOBERFEST-2026.md's weekly-curation step (#1623 action 3) is "every
# Monday, sweep the GFI pool — claim-check stale issues, add 1-2 new starter
# tasks if the pool dips below 8". This is that sweep, so the number in the
# plan is measured rather than remembered. The doc's own count went stale in a
# day: it recorded 6 open (2 tunaos, 4 docs) on 08-13, and on 08-14 the org had
# 13.
#
# Two things a raw count hides, both of which change what a contributor finds:
#
#   * ARCHIVED repos. `letters` is archived, and its GFI issue still appears in
#     an unfiltered org-wide search. The plan's prose already excludes letters,
#     but the announcement URL it tells outreach to publish did not — so a
#     first-timer could click through, pick that issue, and discover they
#     cannot open a PR against it. GitHub search includes archived repos unless
#     told otherwise, so `archived:false` is not optional here.
#   * ASSIGNED issues. An issue someone has claimed is not available, but it
#     still counts toward "the pool is ≥8".
#
# Usage:
#   scripts/gfi-pool-report.sh [threshold]     # default threshold: 8
#
# Exit: 0 pool at or above threshold · 1 below it · 2 could not run.

set -uo pipefail

THRESHOLD="${1:-8}"
ORG="tuna-os"
LABEL="good first issue"

[[ "$THRESHOLD" =~ ^[0-9]+$ ]] || { echo "ERROR: threshold must be a number" >&2; exit 2; }
command -v gh >/dev/null 2>&1 || { echo "ERROR: gh not found" >&2; exit 2; }

# archived:false is the whole point — see the header.
query="is:issue is:open org:${ORG} label:\"${LABEL}\" archived:false"

# Written to a file rather than interpolated into the heredoc below: the
# response contains quotes and newlines, and substituting it into a script body
# corrupts it (the first version of this failed with "could not parse").
resp="$(mktemp)"
trap 'rm -f "$resp"' EXIT
gh api -X GET search/issues -f q="$query" -f per_page=100 >"$resp" 2>/dev/null || {
	echo "ERROR: GitHub search failed (auth? rate limit?)" >&2
	exit 2
}

python3 - "$THRESHOLD" "$resp" <<'PY'
import json, sys, collections
threshold = int(sys.argv[1])
try:
    d = json.load(open(sys.argv[2]))
except Exception as e:
    print(f"ERROR: could not parse search response: {e}", file=sys.stderr); sys.exit(2)

items = d.get("items", [])
total = d.get("total_count", len(items))

by_repo = collections.Counter()
assigned = []
for it in items:
    # repository_url tail is owner/repo
    repo = "/".join(it.get("repository_url", "").split("/")[-2:])
    by_repo[repo] += 1
    if it.get("assignee") or it.get("assignees"):
        assigned.append((repo, it.get("number"), (it.get("title") or "")[:60]))

unassigned = len(items) - len(assigned)

print(f"==> contributable 'good first issue' pool: {total}")
print("    (archived repos excluded — GitHub search includes them by default)")
print()
for repo, n in by_repo.most_common():
    share = 100 * n / len(items) if items else 0
    print(f"    {n:3d}  {repo:<28} {share:4.0f}%")
print()
if assigned:
    print(f"    {len(assigned)} already claimed (assigned) — not available to a newcomer:")
    for repo, num, title in assigned:
        print(f"      {repo}#{num}  {title}")
    print()

# Concentration matters as much as count: a pool that is one repo deep offers
# one kind of task, and a contributor who does not want that kind sees nothing.
if by_repo:
    top_repo, top_n = by_repo.most_common(1)[0]
    if len(items) and top_n / len(items) > 0.6:
        print(f"    NOTE: {top_n}/{len(items)} of the pool is in {top_repo} alone.")
        print(f"          A count above threshold can still be a thin pool.")
        print()

print(f"    unassigned and contributable: {unassigned} (threshold {threshold})")
if unassigned < threshold:
    print(f"==> BELOW THRESHOLD — add {threshold - unassigned} starter task(s).", file=sys.stderr)
    sys.exit(1)
print("==> pool is at or above threshold")
PY
