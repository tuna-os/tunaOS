#!/usr/bin/env bash
# Check the two outreach ledgers and the complete issue history before filing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -eq 0 ]]; then
	echo "Usage: $0 <target or campaign search terms>" >&2
	exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
	echo "ERROR: gh is required to search the issue history" >&2
	exit 2
fi

query="$*"
ledger_files=(
	"$ROOT/docs/ADOPTION-OUTREACH-STATUS.md"
	"$ROOT/docs/README.md"
)

local_matches="$(grep -FinH -- "$query" "${ledger_files[@]}" || true)"
if ! issue_matches="$(
	gh issue list \
		--repo tuna-os/tunaos \
		--state all \
		--label outreach \
		--search "$query in:title" \
		--limit 100 \
		--json number,state,title,url \
		--template '{{range .}}{{printf "#%v [%s] %s — %s\n" .number .state .title .url}}{{end}}'
)"; then
	echo "ERROR: could not search tuna-os/tunaos issue history" >&2
	exit 2
fi

found=0
if [[ -n "$local_matches" ]]; then
	echo "Prepared material or an indexed document already matches:"
	printf '%s\n' "$local_matches"
	found=1
fi
if [[ -n "$issue_matches" ]]; then
	echo "Open or closed outreach issues already match:"
	printf '%s\n' "$issue_matches"
	found=1
fi

if ((found)); then
	echo "Review these results and update the canonical tracker instead of filing a duplicate."
	exit 1
fi

echo "No matching ledger row, indexed document, or outreach issue found for: $query"
