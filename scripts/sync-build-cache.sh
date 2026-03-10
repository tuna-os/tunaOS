#!/usr/bin/env bash

# Sync variant-specific cache to shared cache for deduplication
# Run this after a successful build to promote cached packages to shared layer
# This enables future builds to benefit from deduplication

set -euo pipefail

VARIANT="${1:-}"

if [[ -z "$VARIANT" ]]; then
    echo "Usage: $0 <variant>" >&2
    echo "Example: $0 skipjack" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_BASE="${REPO_ROOT}/.rpm-cache/shared"
CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/${VARIANT}"

if [[ ! -d "$CACHE_VARIANT" ]]; then
    echo "Warning: Variant cache does not exist: $CACHE_VARIANT" >&2
    exit 0
fi

echo "Syncing $VARIANT cache to shared cache for deduplication..."

# Use rsync with hardlinks to deduplicate identical files
# --link-dest creates hardlinks for identical files, saving space
for subdir in dnf libdnf5 rpm; do
    if [[ -d "${CACHE_VARIANT}/${subdir}" ]]; then
        echo "  Syncing ${subdir}..."
        rsync -a --link-dest="${CACHE_VARIANT}/${subdir}/" \
            "${CACHE_VARIANT}/${subdir}/" \
            "${CACHE_BASE}/${subdir}/" 2>/dev/null || true
    fi
done

echo "Cache sync complete. Shared cache now contains deduplicated packages."
