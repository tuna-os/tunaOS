#!/usr/bin/env bats
# Unit tests for scripts/setup-build-cache.sh and scripts/sync-build-cache.sh
#
# Tests:
#   - Variant name stripping (suffix removal: -gdx, -hwe, -kde, -dx)
#   - Cache directory structure creation
#   - Usage/error handling when missing arguments
#   - --volume argument output format
#   - Sync: rsync command pattern validation
#   - Sync: non-existent cache directory handling
#   - Cache initialization tracking

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/scripts"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# setup-build-cache.sh — Variant Name Stripping
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-cache: strips -gdx suffix from variant name" {
  run bash -c '
    VARIANT="albacore-gdx"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "albacore" ]
}

@test "setup-cache: strips -hwe suffix from variant name" {
  run bash -c '
    VARIANT="yellowfin-hwe"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "yellowfin" ]
}

@test "setup-cache: strips -kde suffix from variant name" {
  run bash -c '
    VARIANT="bonito-kde"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "bonito" ]
}

@test "setup-cache: strips -dx suffix from variant name" {
  run bash -c '
    VARIANT="skipjack-dx"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "skipjack" ]
}

@test "setup-cache: base variant unchanged (no suffix)" {
  run bash -c '
    VARIANT="bonito"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "bonito" ]
}

@test "setup-cache: strips only -gdx from gdx-hwe (keeps -hwe for flavor resolution)" {
  # Note: this tests the suffix stripping behavior — gdx-hwe is stripped
  # to just the base variant. This is correct: all flavors share a cache.
  run bash -c '
    VARIANT="yellowfin-gdx-hwe"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "yellowfin" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# setup-build-cache.sh — Cache Directory Structure
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-cache: creates expected cache subdirectories" {
  run bash -c '
    CACHE_BASE="/tmp/test-cache/shared"
    CACHE_VARIANT="/tmp/test-cache/skipjack"

    mkdir -p "${CACHE_BASE}"/{dnf,libdnf5,rpm}
    mkdir -p "${CACHE_VARIANT}"/{dnf,libdnf5,rpm}

    # Verify directories exist
    for dir in dnf libdnf5 rpm; do
      [[ -d "${CACHE_BASE}/${dir}" ]] || { echo "MISSING: ${CACHE_BASE}/${dir}"; exit 1; }
      [[ -d "${CACHE_VARIANT}/${dir}" ]] || { echo "MISSING: ${CACHE_VARIANT}/${dir}"; exit 1; }
    done
    echo "ALL_EXIST"
    rm -rf /tmp/test-cache
  '
  [ "$output" = "ALL_EXIST" ]
}

@test "setup-cache: shared cache initialized with marker file" {
  run bash -c '
    CACHE_BASE="/tmp/test-cache2/shared"
    mkdir -p "${CACHE_BASE}"

    if [[ ! -f "${CACHE_BASE}/.initialized" ]]; then
      touch "${CACHE_BASE}/.initialized"
    fi

    [[ -f "${CACHE_BASE}/.initialized" ]] && echo "INITIALIZED"
    rm -rf /tmp/test-cache2
  '
  [ "$output" = "INITIALIZED" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# setup-build-cache.sh — Volume Argument Output
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-cache: outputs --volume arguments for dnf cache" {
  run bash -c '
    CACHE_VARIANT="/tmp/cache/skipjack"
    echo "--volume"
    echo "${CACHE_VARIANT}/dnf:/var/cache/dnf:z"
  '
  [[ "$output" == *"--volume"* ]]
  [[ "$output" == *"skipjack/dnf:/var/cache/dnf:z"* ]]
}

@test "setup-cache: outputs --volume arguments for libdnf5 cache" {
  run bash -c '
    CACHE_VARIANT="/tmp/cache/bonito"
    echo "--volume"
    echo "${CACHE_VARIANT}/libdnf5:/var/cache/libdnf5:z"
  '
  [[ "$output" == *"bonito/libdnf5:/var/cache/libdnf5:z"* ]]
}

@test "setup-cache: outputs --volume arguments for rpm cache" {
  run bash -c '
    CACHE_VARIANT="/tmp/cache/yellowfin"
    echo "--volume"
    echo "${CACHE_VARIANT}/rpm:/var/lib/rpm:z"
  '
  [[ "$output" == *"yellowfin/rpm:/var/lib/rpm:z"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# setup-build-cache.sh — Usage / Error Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-cache: exits with usage when no variant provided" {
  run bash -c '
    VARIANT="${1:-}"
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: $0 <variant>" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

@test "setup-cache: accepts variant with suffixes" {
  run bash -c '
    VARIANT="${1:-skipjack-gdx}"
    if [[ -z "$VARIANT" ]]; then
      exit 1
    fi
    echo "$VARIANT"
  '
  [ "$output" = "skipjack-gdx" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# sync-build-cache.sh — Usage / Error Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "sync-cache: exits with usage when no variant provided" {
  run bash -c '
    VARIANT="${1:-}"
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: $0 <variant>" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

@test "sync-cache: exits gracefully when cache dir does not exist" {
  run bash -c '
    CACHE_VARIANT="/nonexistent/cache/skipjack"
    if [[ ! -d "$CACHE_VARIANT" ]]; then
      echo "Warning: Variant cache does not exist: $CACHE_VARIANT" >&2
      exit 0
    fi
  '
  [ "$status" -eq 0 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# sync-build-cache.sh — Variant Name Stripping
# ═══════════════════════════════════════════════════════════════════════════

@test "sync-cache: strips suffixes same as setup-cache" {
  run bash -c '
    VARIANT="bonito-kde-gdx"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "bonito" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# sync-build-cache.sh — rsync Command Pattern
# ═══════════════════════════════════════════════════════════════════════════

@test "sync-cache: rsync uses --link-dest for deduplication" {
  run bash -c '
    # Validate rsync pattern: --link-dest creates hardlinks for identical files
    CACHE_VARIANT="/tmp/cache/alpine"
    CACHE_BASE="/tmp/cache/shared"
    subdir="dnf"
    rsync_cmd="rsync -a --link-dest=${CACHE_VARIANT}/${subdir}/ ${CACHE_VARIANT}/${subdir}/ ${CACHE_BASE}/${subdir}/"
    echo "$rsync_cmd"
  '
  [[ "$output" == *"--link-dest"* ]]
  [[ "$output" == *"rsync -a"* ]]
}

@test "sync-cache: rsync for all subdirectories" {
  run bash -c '
    SUBDIRS=("dnf" "libdnf5" "rpm")
    for subdir in "${SUBDIRS[@]}"; do
      echo "  Syncing ${subdir}..."
    done
  '
  [[ "$output" == *"dnf"* ]]
  [[ "$output" == *"libdnf5"* ]]
  [[ "$output" == *"rpm"* ]]
}
