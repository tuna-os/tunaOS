#!/usr/bin/env bash
# Verify that the contributor onboarding labels still expose a usable queue.
# This is intentionally read-only: it reports a regression for a maintainer
# to fix rather than changing issue labels automatically.
set -euo pipefail

repo="${GFI_REPO:-${GITHUB_REPOSITORY:-tuna-os/tunaos}}"
minimum="${GFI_MINIMUM:-3}"

command -v gh >/dev/null || {
	echo "FAIL: gh is required to query the good-first-issue pool" >&2
	exit 1
}
command -v jq >/dev/null || {
	echo "FAIL: jq is required to count the good-first-issue pool" >&2
	exit 1
}

case "$minimum" in
	''|*[!0-9]*)
		echo "FAIL: GFI_MINIMUM must be a non-negative integer" >&2
		exit 1
		;;
esac

count_for_label() {
	local label="$1"
	gh issue list \
		--repo "$repo" \
		--state open \
		--label "$label" \
		--limit 100 \
		--json number \
		| jq 'length'
}

gfi_count=$(count_for_label 'good first issue')
help_count=$(count_for_label 'help wanted')

echo "good first issue: $gfi_count open issue(s)"
echo "help wanted:      $help_count open issue(s)"

if (( gfi_count < minimum || help_count < minimum )); then
	echo "FAIL: each onboarding label must have at least $minimum open issue(s)" >&2
	exit 1
fi

echo "GFI POOL OK: both labels meet the minimum of $minimum"
