#!/usr/bin/env bash
# Advisory reminders for a pull request, derived from the files it touches.
#
# Why this exists
#
# Some conventions here are worth reminding about and not worth blocking a
# merge over: a desktop change that should update the tag docs, a matrix
# change that needs a scope review in green-criteria.yml, a boot-layout
# change that deserves a migration note. A hard gate for any of these would
# fail honest work and train people to add noise to make it green; a
# reminder at the one moment somebody can act cheaply — while the PR is
# open — is what actually keeps the convention alive. This is Hive's
# changelog-reminder shape (kubestellar/hive changelog-reminder.yml), adopted
# in epic #2250 item 11.
#
# It ALWAYS exits 0. That has to hold on a fork PR too, where GITHUB_TOKEN is
# read-only and a comment POST 403s: the reminder is delivered as a job
# summary and a ::notice:: annotation, which need no write permission, and
# the PR comment is attempted on top and its failure tolerated.
# tests/bats/test_pr_nudges.bats runs this against a stubbed `gh` that 403s
# and asserts it still exits 0 — the same regression test Hive added after
# its reminder went red on every external contribution.
#
# Usage:
#   pr-nudges.sh            # read changed paths from stdin, print nudges
#   pr-nudges.sh --deliver  # also write the summary, notice, and (same-repo
#                           # PRs only) one deduplicated PR comment
#
# Environment for --deliver: REPO, PR, GH_TOKEN, IS_FORK (true/false),
# GITHUB_STEP_SUMMARY (optional).

set -uo pipefail

marker='<!-- pr-nudges -->'
deliver=0
[[ "${1:-}" == "--deliver" ]] && deliver=1

mapfile -t files

nudges=()
add() { nudges+=("$1"); }

any() {
	local re="$1" f
	for f in "${files[@]}"; do
		[[ "$f" =~ $re ]] && return 0
	done
	return 1
}

if any '^(manifests/desktops/|build_scripts/desktop/|experiences/)'; then
	add "**Desktop change.** If what a flavor ships changed, check \`docs/IMAGE-TAGS.md\`, the README variant table, and the desktop contract in \`build_scripts/checks/verify-desktop-experience.sh\` still describe it."
fi

if any '^\.github/build-config\.yml$'; then
	add "**Matrix change.** A new variant or flavor needs: a \`scope\` review in \`.github/green-criteria.yml\` (which axes CI can actually assert for it), a row in the README table, and \`docs/HARDWARE.md\` if the hardware story changed. \`docs/MATRIX-STATUS.md\` is generated — do not edit it by hand."
fi

if any '^(scripts/iso-e2e\.sh|scripts/installer-walkthrough\.py|live-iso/|tests/installer-screens\.yaml)'; then
	add "**Installer / live ISO change.** \`docs/INSTALLER_SCREENSHOTS.md\` and \`tests/installer-screens.yaml\` describe what the installer looks like; if a screen moved, they are stale."
fi

if any '^(Containerfile|system_files/usr/lib/bootc/install/|build_scripts/bootc/|system_files/usr/lib/systemd/)'; then
	add "**Boot / install layout change.** If an existing install would behave differently after \`bootc upgrade\`, add a note to \`MIGRATION.md\` or the release notes. Breaking changes need a migration note, not just a commit message."
fi

if any '^\.github/workflows/'; then
	add "**Workflow change.** If a green gate moved, update its \`gates\` block in \`.github/green-criteria.yml\` — \`tests/test_ci_contract.py\` fails when the two disagree. \`docs/PIPELINE.md\` and \`docs/build-pipeline.md\` describe the pipeline for humans."
fi

if any '^(scripts/|build_scripts/|Containerfile)' && ! any '(^docs/|\.md$)'; then
	add "**Docs.** This PR changes build or pipeline code and no documentation. If the behavior is visible to a user or a contributor, say where it is documented (or that it is not user-visible)."
fi

if [[ ${#nudges[@]} -eq 0 ]]; then
	echo "no nudges for this change"
	exit 0
fi

body_file="$(mktemp)"
{
	echo "$marker"
	echo "### Reminders for this PR"
	echo
	for n in "${nudges[@]}"; do
		echo "- $n"
	done
	echo
	echo "_These are reminders, not gates; they never block a merge. Derived from the changed paths by \`.github/scripts/pr-nudges.sh\`._"
} >"$body_file"

grep -v "^${marker}$" "$body_file"

if [[ "$deliver" -ne 1 ]]; then
	rm -f "$body_file"
	exit 0
fi

# Deliver somewhere that always works, first. The summary and the annotation
# need no write permission, so they reach fork PRs and same-repo branches
# identically.
grep -v "^${marker}$" "$body_file" >>"${GITHUB_STEP_SUMMARY:-/dev/null}"
echo "::notice title=PR reminders::${#nudges[@]} reminder(s) for the paths this PR touches; see the job summary. Not a gate."

if [[ "${IS_FORK:-false}" == "true" ]]; then
	echo "fork PR — GITHUB_TOKEN is read-only here, so the reminders were delivered as a job summary and annotation instead of a comment"
	rm -f "$body_file"
	exit 0
fi

# Same-repo PR: one comment, only once. A reminder that reappears on every
# push is noise, and noise is how conventions die.
if gh api --paginate "repos/${REPO}/issues/${PR}/comments" --jq '.[].body' 2>/dev/null | grep -qF "$marker"; then
	echo "already reminded"
	rm -f "$body_file"
	exit 0
fi

# Tolerated, not asserted: an org policy can narrow GITHUB_TOKEN even on a
# same-repo PR, and the reminder has already been delivered above.
if ! gh api "repos/${REPO}/issues/${PR}/comments" -F body=@"$body_file"; then
	echo "::notice::could not post the reminders as a PR comment; they are in this job's summary instead"
fi
rm -f "$body_file"
exit 0
