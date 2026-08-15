#!/usr/bin/env bash
# check-workflow-push.sh — can this token push a workflow-file change?
#
# tunaOS#1557 records that pushes touching .github/workflows/*.yml were rejected
# with
#
#   refusing to allow a GitHub App to create or update workflow ...
#   without workflows permission
#
# and that the workaround in use was posting the patch as an issue comment.
# docs/CI-WORKFLOW-PUBLISHING.md (#1614) covers what to do about a rejection.
# What was missing is the step before that: knowing whether you are actually
# rejected. The cost of guessing wrong is asymmetric —
#
#   * assume you CAN and you cannot: one failed push, then you read the runbook;
#   * assume you CANNOT and you can: the fix strands in a comment, where #1390
#     and #1430 sat until someone re-did them as #1621 and #1622.
#
# The second is the expensive one and it is the one that happened. So: measure
# instead of assuming. There is no API that answers this reliably — the App's
# effective permission is not readable from inside a job — so the honest test is
# to attempt the push, which is what the runbook's own step 3 asks for.
#
# This pushes a throwaway branch to YOUR FORK and deletes it again. It never
# touches upstream and never opens a PR.
#
# Usage:
#   scripts/check-workflow-push.sh [remote]     # default remote: origin
#
# Exit codes:
#   0  workflow files are pushable to <remote>
#   1  push rejected for lack of `workflows` permission — see the runbook
#   2  could not run the check (dirty tree, no remote, no workflow file)

set -uo pipefail

REMOTE="${1:-origin}"
RUNBOOK="docs/CI-WORKFLOW-PUBLISHING.md"

die() {
	echo "ERROR: $*" >&2
	exit 2
}

command -v git >/dev/null 2>&1 || die "git not found"
git rev-parse --git-dir >/dev/null 2>&1 || die "not inside a git repository"

# A dirty tree would get swept into the probe commit. Refuse rather than commit
# someone's work-in-progress to a branch this script then deletes.
if [[ -n "$(git status --porcelain)" ]]; then
	die "working tree is dirty — commit or stash first (this script commits and pushes)"
fi

git remote get-url "$REMOTE" >/dev/null 2>&1 || die "no such remote: ${REMOTE}"

# Probe an existing workflow so the push carries a real workflow-file change.
# Creating a new file would test the same permission, but touching one that is
# already tracked keeps the diff to a single appended comment line.
PROBE_FILE="$(git ls-files '.github/workflows/*.yml' | head -1)"
[[ -n "$PROBE_FILE" ]] || die "no .github/workflows/*.yml tracked in this repo"

START_REF="$(git rev-parse --abbrev-ref HEAD)"
BRANCH="wf-push-probe-$$"

cleanup() {
	git checkout -q "$START_REF" 2>/dev/null || true
	git branch -qD "$BRANCH" 2>/dev/null || true
	# Best effort: if the push DID land, take it back off the fork.
	git push -q "$REMOTE" --delete "$BRANCH" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> probing ${REMOTE} with a one-line change to ${PROBE_FILE}"
git checkout -q -b "$BRANCH" || die "could not create probe branch"
printf '\n# workflow-push permission probe (tunaOS#1557) — not intended to merge\n' >>"$PROBE_FILE"
git commit -q -am "probe: workflow-file push permission check" || die "probe commit failed"

push_output="$(git push "$REMOTE" "$BRANCH" 2>&1)"
push_rc=$?

if [[ "$push_rc" -eq 0 ]]; then
	echo "==> RESULT: workflow files ARE pushable to '${REMOTE}'."
	echo "    Open the fix as a normal fork PR. Do not park the patch in an issue"
	echo "    comment — that is how #1390 and #1430 stranded."
	exit 0
fi

# Distinguish the permission rejection from every other push failure. Only the
# first means "workflow files specifically are blocked"; the rest are ordinary
# problems a runbook about App permissions will not solve.
if grep -qiE 'without .?workflows.? permission|refusing to allow (a|an) (GitHub App|OAuth App|integration) to (create or update )?workflow' <<<"$push_output"; then
	echo "==> RESULT: push REJECTED for lack of 'workflows' permission." >&2
	echo "$push_output" | sed 's/^/    /' >&2
	echo "    See ${RUNBOOK} — a workflow YAML permissions: block cannot grant" >&2
	echo "    this; it is an App-level setting." >&2
	exit 1
fi

echo "==> Push failed, but NOT for the workflows permission:" >&2
echo "$push_output" | sed 's/^/    /' >&2
echo "    That is an ordinary push problem (auth, network, branch protection)," >&2
echo "    not the #1557 condition. The runbook will not help." >&2
exit 2
