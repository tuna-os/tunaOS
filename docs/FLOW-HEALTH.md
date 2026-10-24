# PR flow health

This runbook gives the procedure recommended in
[#3140](https://github.com/tuna-os/tunaos/issues/3140). Its 2026-10-10 snapshot
is historical evidence, not a current queue count. The issue separates PRs
whose CI passes, with no merge conflict and no hold from the hold backlog in
[#2881](https://github.com/tuna-os/tunaos/issues/2881) and
[#3009](https://github.com/tuna-os/tunaos/issues/3009).

## Author preflight

Guide, strategist, architect, and other authors check open PRs before they edit
and again before they open a PR. Search by changed paths as well as titles.
For example, list every open PR, then check each for `ROADMAP.md`:

```bash
set -euo pipefail
repo=tuna-os/tunaos
target=ROADMAP.md
pr_numbers=$(gh api --paginate "repos/$repo/pulls?state=open&per_page=100" \
  --jq '.[].number')
for number in $pr_numbers; do
  matches=$(gh api --paginate "repos/$repo/pulls/$number/files?per_page=100" \
    --jq ".[] | select(.filename == \"$target\" or .previous_filename == \"$target\") | .filename")
  if [[ -n "$matches" ]]; then
    gh pr view "$number" --repo "$repo" --json number,url,title,baseRefName
  fi
done
```

Run this in Bash with `gh` authenticated. Set `repo` and `target` to the
repository and path you will change. Repeat for each planned path. Both
requests use pagination. If a request fails, stop and fix access before you
conclude there is no overlap.

GitHub limits the files endpoint to 3,000 files; inspect a local diff for a
larger PR. The scan is a point-in-time check.

Read the matching PR's body, discussion, target branch, and diff. Use
`gh pr diff NUMBER --repo "$repo"` to compare the proposed changes.

- **Same deliverable:** add missing evidence or a correction to the existing
  PR discussion. Link it from your task issue. Do not open another refresh.
  If you cannot update that branch, leave a patch or exact change suggestion.
- **Distinct deliverable:** file overlap alone is not duplication. Explain
  the difference and link the related PR in your PR body. Coordinate edits
  to the shared section before you open the PR.
- **Conflict or replacement:** identify which claims differ and cite
  the evidence. Ask the author or an authorized reviewer to select a PR.
  Preserve unique changes and discussion before closure. Do not close another
  contributor's PR because of its age.

## Review sweep

During weekly contributor triage, the maintainer or a reviewer with permission
checks PRs whose CI passes and which have no hold. An org coordinator
repeats this in the authorized repositories and records the scope. This
runbook grants no review, label, closure, or merge permission elsewhere.

1. Start with the `refactor-docs` class: docs, roadmaps, and plans.
   This was the largest class in the issue's snapshot. Read the diff; a docs
   label does not prove low risk or accuracy.
2. Group PRs by deliverable and changed paths. Use the author preflight to
   find candidates. Compare diffs before you choose one PR to carry a refresh.
   Link the chosen PR and any unique work to preserve in each disposition.
3. Check current CI, merge conflicts, reviews, labels, and dependencies. Route
   held PRs to the [hold-review sweep](../CONTRIBUTING.md#weekly-hold-review-sweep).
   Request missing review on PRs that meet the checks. Record blockers with
   an owner and an observable next action.
4. An authorized maintainer may merge after the required checks and approvals.
   Contributors never merge their own PRs or bypass write gates. Age and green
   CI alone do not authorize a merge.

## Fourteen-day follow-up

The triage maintainer records the sweep date, measurement owner, and next
measurement date in the task issue. Repeat the measurement 14 days after
each baseline. The initial follow-up to the issue's 2026-10-10 snapshot is
2026-10-24. If that date passes without a report, take a fresh baseline and
state the missed measurement. Do not infer improvement from elapsed time.

Use the same Hive flow-health census and authorized repository set as the
baseline when available. Save the command or tool version, filters, raw
results, and UTC capture time with the report. If the original census or
scope is unavailable, mark the comparison unavailable and establish a new
baseline. A count from one repository is not an org-wide rerun.

For a GitHub check of an individual candidate, collect:

```bash
gh pr view NUMBER --repo tuna-os/tunaos \
  --json number,url,createdAt,headRefOid,isDraft,labels,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup
gh pr checks NUMBER --repo tuna-os/tunaos --required
```

Keep unknown mergeability, absent checks, incomplete or failed checks, drafts,
holds, and unresolved dependencies separate from the green, mergeable queue.
Verify checks against the current head and branch rules. An empty check list
does not prove CI passed. Record required approvals still missing; mergeability
does not mean review requirements are met. Record missing access as a scope
gap, not a zero. The GitHub fields do not include Hive's `review_class`; do
not claim an exact class comparison from GitHub data alone.

The dated report links the source evidence and includes:

- Repositories covered, omissions, and the exact candidate filters.
- Green and mergeable PR count; age median, mean, oldest, and counts over
  24 and 48 hours. Age is capture time minus `createdAt`, not last update.
  For an even-sized set, average the two middle ages; for an empty set,
  report age statistics as unavailable.
- Duplicate refresh groups and excess PRs: group by repository, target
  branch, and verified deliverable. Count a group of `n` PRs as one group
  and `n - 1` excess PRs. Include held duplicates separately. A shared path
  identifies a candidate, not a confirmed duplicate.
- Intake and merges over the same 14-day window, review dispositions, and
  links to the reviewed sample. Record merge timestamps and actual merges;
  closed duplicate PRs do not count as merges.
- Change since the baseline in median age and duplicate counts, with the
  next owner and date.

Lower age and duplicate counts support the review-capacity diagnosis
when merges keep pace with intake. If the queue stays flat or grows
after active review, ask the maintainer to audit merge grants and automerge
governor settings. Link actual review and merge evidence. Dwell time alone
does not prove a missing grant or a disabled governor. Keep this follow-up
in the existing task issue; do not file another roadmap refresh to
report the same queue.
