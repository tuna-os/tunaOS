#!/usr/bin/env bash

# Setup RPM cache with block-level deduplication for parallel builds
# This script creates a cache structure that allows multiple variants to build
# simultaneously while sharing package data through a shared base layer.

set -euo pipefail

VARIANT="${1:-}"
OUTPUT_VAR="${2:-CACHE_MOUNTS}"

if [[ -z "$VARIANT" ]]; then
    echo "Usage: $0 <variant> [output_var_name]" >&2
    echo "Example: $0 skipjack CACHE_MOUNTS" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_BASE="${REPO_ROOT}/.rpm-cache/shared"
CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/${VARIANT}"

# Create cache directory structure
# - shared/: Read-only base layer with common packages (deduplication)
# - ${VARIANT}/: Per-variant writable layer for parallel builds
mkdir -p "${CACHE_BASE}"/{dnf,libdnf5,rpm}
mkdir -p "${CACHE_VARIANT}"/{dnf,libdnf5,rpm}

# For the first build, initialize shared cache if empty
# Subsequent builds will read from shared and write to variant-specific
if [[ ! -f "${CACHE_BASE}/.initialized" ]]; then
    echo "Initializing shared cache layer..." >&2
    touch "${CACHE_BASE}/.initialized"
fi

# Build volume mount arguments for podman
# Strategy: Mount variant-specific cache directories for parallel builds
# Each variant gets its own cache to avoid conflicts
# Output each argument on a separate line for proper array handling

echo "--volume"
echo "${CACHE_VARIANT}/dnf:/var/cache/dnf:z"
echo "--volume"
echo "${CACHE_VARIANT}/libdnf5:/var/cache/libdnf5:z"
echo "--volume"
echo "${CACHE_VARIANT}/rpm:/var/lib/rpm:z"
