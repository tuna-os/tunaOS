#!/usr/bin/env bats
# actions/checkout does not leave a usable token behind (tunaOS#1180).
#
# By default actions/checkout writes the job's token into .git/config, so every
# later step — including anything a build script pulls in — can push with it.
# `persist-credentials: false` turns that off, and PR #1434 set it on the
# checkouts that do not need it.
#
# The reason this is a test and not just a diff: the change LOOKS unfinished.
# Nine checkout steps still lack the flag, which reads like an oversight and
# invites someone to "complete" it. Every one of those nine is in a workflow
# that pushes back to the repository — commits, `git push`,
# create-pull-request — so adding the flag there would break all nine.
#
# So the rule is not "every checkout sets it". It is "every checkout sets it
# unless the workflow writes back to refs", and that is what is asserted, with
# the write-back set derived from the workflows rather than hardcoded — a
# hardcoded allowlist would be one more thing to drift.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WF="${REPO_ROOT}/.github/workflows"

# Does this workflow push commits/refs back to the repo?
writes_back() {
  grep -qE 'git push|git commit|gh pr create|peter-evans/create-pull-request|EndBug/add-and-commit' "$1"
}

# Checkout steps in $1 that do NOT set persist-credentials within the step.
unflagged_checkouts() {
  awk '
    /uses: *actions\/checkout/ { c = NR; total++ }
    c && NR > c && NR <= c + 6 && /persist-credentials/ { flagged++; c = 0 }
    END { print (total + 0) - (flagged + 0) }
  ' "$1"
}

@test "there are workflows to check (guards a vacuous pass)" {
  run bash -c "grep -lE 'uses: *actions/checkout' '$WF'/*.yml | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -gt 20 ]
}

@test "read-only workflows check out without persisting credentials" {
  local offenders=0 f
  for f in "$WF"/*.yml; do
    writes_back "$f" && continue
    if [ "$(unflagged_checkouts "$f")" -gt 0 ]; then
      echo "MISSING persist-credentials: false — $(basename "$f") does not write back to refs" >&2
      offenders=$((offenders + 1))
    fi
  done
  [ "$offenders" -eq 0 ]
}

@test "the exclusions are exactly the workflows that push back" {
  # Documents WHY the nine are excluded, and fails if one of them stops
  # pushing (at which point it should get the flag) or if a new unflagged
  # checkout appears in a workflow that does not push.
  local f n listed=0
  for f in "$WF"/*.yml; do
    n="$(unflagged_checkouts "$f")"
    [ "$n" -gt 0 ] || continue
    listed=$((listed + 1))
    if ! writes_back "$f"; then
      echo "UNEXPLAINED: $(basename "$f") has an unflagged checkout but never pushes" >&2
      return 1
    fi
  done
  # Non-zero on purpose: if this hits zero because someone flagged every
  # checkout including the push-back ones, those workflows are broken and the
  # test above would not have caught it.
  [ "$listed" -gt 0 ]
}

@test "both sides of the rule are populated" {
  # If every workflow wrote back, or none did, the rule would be untested.
  local rw=0 ro=0 f
  for f in "$WF"/*.yml; do
    grep -qE 'uses: *actions/checkout' "$f" || continue
    if writes_back "$f"; then rw=$((rw + 1)); else ro=$((ro + 1)); fi
  done
  [ "$rw" -gt 0 ]
  [ "$ro" -gt 0 ]
}
