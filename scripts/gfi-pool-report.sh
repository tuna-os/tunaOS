#!/usr/bin/env bash
# gfi-pool-report.sh — test the live starter-task pool against its contract.
#
# A launch-ready task is open, unassigned, and has both `good first issue` and
# `help wanted`. GitHub search includes archived repositories unless the query
# excludes them. The report also checks repository breadth and concentration;
# a large count in one repository is not a useful organization-wide pool.
#
# Usage:
#   scripts/gfi-pool-report.sh [minimum-tasks] [minimum-repositories]
#
# Defaults are the weekly maintenance floor (8 tasks across 3 repositories).
# For the Q4 strategic target, run:
#   scripts/gfi-pool-report.sh 15 6
#
# Exit: 0 contract met · 1 contract not met · 2 report could not run.

set -uo pipefail

MIN_TASKS="${1:-8}"
MIN_REPOS="${2:-3}"
ORG="tuna-os"
LABEL="good first issue"

for value in "$MIN_TASKS" "$MIN_REPOS"; do
	[[ "$value" =~ ^[0-9]+$ ]] || {
		echo "ERROR: thresholds must be numbers" >&2
		exit 2
	}
done
command -v gh >/dev/null 2>&1 || {
	echo "ERROR: gh not found" >&2
	exit 2
}

query="is:issue is:open org:${ORG} label:\"${LABEL}\" archived:false"
resp="$(mktemp)"
trap 'rm -f "$resp"' EXIT
gh api -X GET search/issues -f q="$query" -f per_page=100 >"$resp" 2>/dev/null || {
	echo "ERROR: GitHub search failed (auth? rate limit?)" >&2
	exit 2
}

python3 - "$MIN_TASKS" "$MIN_REPOS" "$resp" <<'PY'
import collections
import json
import sys

minimum_tasks = int(sys.argv[1])
minimum_repositories = int(sys.argv[2])
try:
    with open(sys.argv[3], encoding="utf-8") as response:
        data = json.load(response)
except Exception as error:
    print(f"ERROR: could not parse search response: {error}", file=sys.stderr)
    sys.exit(2)

items = data.get("items", [])
total = data.get("total_count", len(items))
if total > len(items):
    print(
        f"ERROR: search returned {total} issues but only {len(items)} were fetched",
        file=sys.stderr,
    )
    sys.exit(2)

available_by_repo = collections.Counter()
ready_by_repo = collections.Counter()
claimed = []
missing_help = []

for item in items:
    repo = "/".join(item.get("repository_url", "").split("/")[-2:])
    number = item.get("number")
    title = (item.get("title") or "")[:60]
    assigned = bool(item.get("assignee") or item.get("assignees"))
    labels = {
        label.get("name", "").casefold()
        for label in item.get("labels", [])
        if isinstance(label, dict)
    }

    if assigned:
        claimed.append((repo, number, title))
        continue

    available_by_repo[repo] += 1
    if "help wanted" in labels:
        ready_by_repo[repo] += 1
    else:
        missing_help.append((repo, number, title))

available = sum(available_by_repo.values())
ready = sum(ready_by_repo.values())
breadth = len(ready_by_repo)
top_repo, top_count = ready_by_repo.most_common(1)[0] if ready_by_repo else ("—", 0)
top_share = top_count / ready if ready else 0

print("==> live good-first-issue completeness check")
print("    archived repositories and assigned issues are excluded")
print("    launch-ready means both 'good first issue' and 'help wanted'")
print()
print(f"    {'repository':<32} {'available GFI':>13} {'launch-ready':>13}")
for repo in sorted(set(available_by_repo) | set(ready_by_repo)):
    print(f"    {repo:<32} {available_by_repo[repo]:>13} {ready_by_repo[repo]:>13}")
print()
print(f"    unassigned GFI: {available}")
print(f"    launch-ready: {ready} (minimum {minimum_tasks})")
print(f"    repository breadth: {breadth} (minimum {minimum_repositories})")
if ready:
    print(f"    largest share: {top_repo} has {top_count}/{ready} ({top_share:.0%}; maximum 50%)")

if missing_help:
    print()
    print("    Unassigned GFI missing 'help wanted':")
    for repo, number, title in missing_help:
        print(f"      {repo}#{number}  {title}")
if claimed:
    print()
    print("    Assigned GFI (not available):")
    for repo, number, title in claimed:
        print(f"      {repo}#{number}  {title}")

failures = []
if ready < minimum_tasks:
    failures.append(f"add {minimum_tasks - ready} launch-ready task(s)")
if breadth < minimum_repositories:
    failures.append(
        f"add launch-ready tasks in {minimum_repositories - breadth} more repository/repositories"
    )
if top_share > 0.5:
    failures.append("reduce the largest repository share to 50% or less")

if failures:
    print()
    print("==> INCOMPLETE — " + "; ".join(failures), file=sys.stderr)
    sys.exit(1)

print()
print("==> pool meets the requested completeness contract")
PY
