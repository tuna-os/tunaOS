#!/usr/bin/env bash
# Reject newly added bare `|| true` suppressions in build automation.
# Existing suppressions are tracked by issue #1652 and require individual
# triage; this guard prevents the inventory from growing while that work
# proceeds.
set -euo pipefail

if ! git rev-parse --verify HEAD^ >/dev/null 2>&1; then
    echo "No parent commit available; skipping new suppression check."
    exit 0
fi

violations=$(git diff --unified=0 HEAD^ HEAD -- \
    '.github/workflows/*.yml' '.github/workflows/*.yaml' \
    'Justfile' 'just/*.just' \
    | grep -E '^\+[^+].*\|\|[[:space:]]*true([[:space:]]|$|[;)])' || true)

if [[ -n "${violations}" ]]; then
    echo "ERROR: newly added bare '|| true' suppressions are not allowed:" >&2
    echo "${violations}" >&2
    echo "Use an explicit, named non-fatal guard with a visible warning, or let the command fail." >&2
    exit 1
fi

echo "No new bare '|| true' suppressions found."
