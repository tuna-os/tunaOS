#!/usr/bin/env bats
# The workflow-push preflight (tunaOS#1557).
#
# #1557's real cost was not the rejected push — it was the response to it:
# patches for #1390 and #1430 parked in issue comments, where they sat until
# someone re-did them as #1621 and #1622. Both of those turned out to be
# pushable (#1621 pushed .github/workflows/catalog-facts.yml from a fork;
# #1622 pushed two workflow files to an upstream branch), so the work was
# stranded on an assumption rather than a measurement.
#
# scripts/check-workflow-push.sh measures instead. These tests cover the parts
# that need no network: the refusals, and the classifier that separates "the
# App lacks workflows permission" from an ordinary push failure — because
# telling a user to go read an App-permission runbook when their real problem
# is a bad credential wastes exactly the time this script exists to save.
#
# The push path itself is not covered here; it needs a real remote, which is
# what the script is for.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-workflow-push.sh"

@test "the script exists, is executable, and is valid bash" {
  [ -x "$SCRIPT" ]
  run bash -n "$SCRIPT"
  [ "$status" -eq 0 ]
}

# A throwaway repo with one tracked workflow file, so the script gets far
# enough to reach the checks under test.
make_repo() {
  local r="${BATS_TEST_TMPDIR}/repo"
  mkdir -p "$r/.github/workflows"
  cd "$r" || return 1
  git init -q .
  git config user.email t@example.com
  git config user.name t
  printf 'name: t\non: push\njobs: {}\n' > .github/workflows/t.yml
  git add -A && git commit -qm init
  echo "$r"
}

@test "refuses on a dirty tree instead of committing someone's work in progress" {
  # The script commits -a. Sweeping unrelated changes into a branch it then
  # deletes would lose them.
  local r; r="$(make_repo)"
  cd "$r" || return 1
  echo "uncommitted" > scratch.txt
  run bash "$SCRIPT" origin
  [ "$status" -eq 2 ]
  [[ "$output" == *"dirty"* ]]
}

@test "refuses when the named remote does not exist" {
  local r; r="$(make_repo)"
  cd "$r" || return 1
  run bash "$SCRIPT" nosuchremote
  [ "$status" -eq 2 ]
  [[ "$output" == *"no such remote"* ]]
}

@test "refuses when the repo tracks no workflow file to probe with" {
  local r="${BATS_TEST_TMPDIR}/bare"
  mkdir -p "$r"; cd "$r" || return 1
  git init -q .; git config user.email t@example.com; git config user.name t
  echo hi > README.md; git add -A; git commit -qm init
  git remote add origin https://example.invalid/x.git
  run bash "$SCRIPT" origin
  [ "$status" -eq 2 ]
  [[ "$output" == *"no .github/workflows"* ]]
}

# ── the classifier ────────────────────────────────────────────────────────
#
# Extracted from the script rather than retyped, so it cannot drift from the
# code it is asserting about.

classifier() {
  grep -oE "grep -qiE '[^']+'" "$SCRIPT" | head -1 | sed "s/^grep -qiE '//; s/'$//"
}

matches() { # message -> 0 if classified as the permission rejection
  local pat; pat="$(classifier)"
  [ -n "$pat" ] || return 2
  grep -qiE "$pat" <<<"$1"
}

@test "the classifier pattern is extractable" {
  run classifier
  [ "$status" -eq 0 ]
  [ -n "$output" ]
}

@test "GitHub's actual refusal message is classified as the permission problem" {
  # The message quoted in #1557.
  run matches "! [remote rejected] br -> br (refusing to allow a GitHub App to create or update workflow \`.github/workflows/x.yml\` without \`workflows\` permission)"
  [ "$status" -eq 0 ]
  # OAuth apps and integrations word it differently for the same cause.
  run matches "refusing to allow an OAuth App to create or update workflow \`.github/workflows/x.yml\` without \`workflow\` scope"
  [ "$status" -eq 0 ]
}

@test "ordinary push failures are NOT classified as the permission problem" {
  # Sending someone to an App-permission runbook for a bad credential or a
  # protected branch is worse than saying nothing.
  run matches "remote: Invalid username or password. fatal: Authentication failed"
  [ "$status" -ne 0 ]
  run matches "! [remote rejected] main -> main (protected branch hook declined)"
  [ "$status" -ne 0 ]
  run matches "fatal: unable to access 'https://github.com/x.git/': Could not resolve host: github.com"
  [ "$status" -ne 0 ]
  run matches "! [rejected] main -> main (non-fast-forward)"
  [ "$status" -ne 0 ]
}

@test "the three outcomes use distinct exit codes" {
  # 0 pushable / 1 permission-rejected / 2 could not run. A caller that cannot
  # tell 1 from 2 will send people to the wrong runbook.
  run grep -cE '^(	)?exit [012]$' "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$output" -ge 3 ]
}
