#!/usr/bin/env bats
# The Hacktoberfest announcement points somewhere contributable (tunaOS#1623).
#
# docs/HACKTOBERFEST-2026.md already knows `letters` is archived — it removed it
# from the repository list on 2026-08-12. The org-wide filtered view it tells
# outreach to publish did not know: GitHub issue search includes archived
# repositories unless given `archived:false`, so the announced link still
# offered that repo's `good first issue`. Measured 2026-08-14: 13 results
# unfiltered, 12 filtered.
#
# A first-time contributor clicking the announced link, picking that issue, and
# finding they cannot open a pull request is the precise experience a
# Hacktoberfest plan exists to prevent — and it is invisible in review, because
# the URL looks right.
#
# The pool COUNT is deliberately not asserted here. It moves daily (6 on 08-13,
# 12 on 08-14), and a test that pins it would be red most mornings for no
# reason. scripts/gfi-pool-report.sh measures it on demand instead; these tests
# cover the things that should not move.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
PLAN="${REPO_ROOT}/docs/HACKTOBERFEST-2026.md"
SWEEP="${REPO_ROOT}/scripts/gfi-pool-report.sh"

@test "the plan exists and names a filtered issue view" {
  [ -f "$PLAN" ]
  run grep -c 'github.com/issues?q=' "$PLAN"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "every announced issue-search URL excludes archived repositories" {
  # The whole finding. Any org-wide search URL in this doc is something outreach
  # may publish, so all of them need the filter, not just the one that had it
  # pointed out.
  local bad=0 url
  while read -r url; do
    [[ "$url" == *"archived%3Afalse"* || "$url" == *"archived:false"* ]] && continue
    echo "UNFILTERED: $url" >&2
    bad=$((bad + 1))
  done < <(grep -oE 'https://github\.com/issues\?q=[^ >)]+' "$PLAN")
  [ "$bad" -eq 0 ]
}

@test "the plan says why the filter is there" {
  # Without the reason, the next person tidying the URL drops it again.
  run grep -F 'archived:false' "$PLAN"
  [ "$status" -eq 0 ]
  # Matched on one line — the sentence wraps, and grep is line-oriented. (This
  # test failed on its own first run for exactly that reason.)
  run grep -Fi 'is load-bearing' "$PLAN"
  [ "$status" -eq 0 ]
}

@test "the archived repo is not offered as a candidate" {
  # letters is archived; it must not appear as a live row in the candidate
  # table. Struck-through mentions in the prose are fine and deliberate.
  run bash -c "grep -E '^\| \[?letters' '$PLAN' | grep -v '~~'"
  [ "$status" -ne 0 ]
}

# ── the sweep script ──────────────────────────────────────────────────────

@test "the sweep script exists, is executable, and is valid bash" {
  [ -x "$SWEEP" ]
  run bash -n "$SWEEP"
  [ "$status" -eq 0 ]
}

@test "the sweep applies the archived filter it exists to apply" {
  run grep -F 'archived:false' "$SWEEP"
  [ "$status" -eq 0 ]
}

@test "the sweep rejects a non-numeric threshold instead of defaulting" {
  # A silently-defaulted threshold would report "above threshold" against a
  # number nobody chose.
  run bash "$SWEEP" not-a-number
  [ "$status" -eq 2 ]
  [[ "$output" == *"must be a number"* ]]
}

@test "the plan points at the sweep rather than asking for a manual count" {
  # #1623 action 3 is a weekly sweep. The doc's own count was a day stale when
  # I checked it; a documented command is what keeps that from repeating.
  run grep -F 'gfi-pool-report.sh' "$PLAN"
  [ "$status" -eq 0 ]
}
