#!/usr/bin/env bash
# Run the same pinned Simplified Technical English linter as CI.
#
# The linter lives in tuna-os/.github, not in this repository. Cache that
# shared source at the exact workflow pin so local checks use the CI rules
# without copying a second implementation into TunaOS. The cache is outside
# the worktree and never becomes source content.

set -Eeuo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ste_workflow="${repo_root}/.github/workflows/ste.yml"
ste_ref="$(sed -nE \
	's|^[[:space:]]*uses: tuna-os/\.github/\.github/workflows/ste-lint\.yml@([0-9a-f]{40}).*$|\1|p' \
	"$ste_workflow" | head -n 1)"

if [[ ! "$ste_ref" =~ ^[0-9a-f]{40}$ ]]; then
	echo "ERROR: could not read the pinned STE workflow revision from ${ste_workflow}" >&2
	exit 1
fi

budget="$(tr -d '[:space:]' <"${repo_root}/.ste-budget")"
if [[ ! "$budget" =~ ^[0-9]+$ ]]; then
	echo "ERROR: .ste-budget must contain one non-negative integer" >&2
	exit 1
fi

if [[ -n "${TUNAOS_STE_CACHE_DIR:-}" ]]; then
	cache_root="$TUNAOS_STE_CACHE_DIR"
elif [[ -n "${XDG_CACHE_HOME:-}" ]]; then
	cache_root="${XDG_CACHE_HOME}/tunaos/ste-lint"
else
	cache_root="${TMPDIR:-/tmp}/tunaos-ste-lint-$(id -u)"
fi
cache_dir="${cache_root}/${ste_ref}"
linter="${cache_dir}/.github/actions/ste-lint/ste-lint.mjs"

if [[ ! -f "$linter" ]]; then
	if [[ -e "$cache_dir" ]]; then
		echo "ERROR: STE cache exists but is incomplete: ${cache_dir}" >&2
		echo "Remove that cache directory and run 'just ste' again." >&2
		exit 1
	fi
	mkdir -p "$cache_root"
	echo "Fetching shared STE linter at ${ste_ref} into the local cache..." >&2
	git clone --quiet --filter=blob:none --no-checkout \
		https://github.com/tuna-os/.github.git "$cache_dir"
	git -C "$cache_dir" fetch --quiet --filter=blob:none origin "$ste_ref"
	git -C "$cache_dir" checkout --quiet --detach "$ste_ref"
fi

if [[ ! -f "$linter" ]]; then
	echo "ERROR: shared STE linter is missing from ${cache_dir}" >&2
	exit 1
fi

if ! command -v node >/dev/null 2>&1; then
	echo "ERROR: node is required for the STE linter; run 'just setup'" >&2
	exit 1
fi

echo "Checking Simplified Technical English (budget: ${budget})..."
node "$linter" --summary
node "$linter" --max "$budget" >/dev/null
