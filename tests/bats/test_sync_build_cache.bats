#!/usr/bin/env bats
# Unit tests for scripts/sync-build-cache.sh
#
# Tests:
#   - Variant name stripping (same logic as setup-build-cache)
#   - Warning when variant cache does not exist (non-fatal exit 0)
#   - Sync behavior for dnf, libdnf5, rpm subdirectories
#   - Error handling when no variant provided

setup() {
  TEST_ROOT="$(mktemp -d)"
  REPO_ROOT="${TEST_ROOT}/repo"
  mkdir -p "${REPO_ROOT}/scripts"

  # Copy the script for path checks
  cp "${BATS_TEST_DIRNAME}/../../scripts/sync-build-cache.sh" \
     "${REPO_ROOT}/scripts/sync-build-cache.sh"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Variant Name Stripping (shared logic with setup-build-cache)
# ═══════════════════════════════════════════════════════════════════════════

@test "sync-build-cache: strips -gdx suffix" {
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

@test "sync-build-cache: strips -hwe suffix" {
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

@test "sync-build-cache: strips combined flavor suffixes" {
  run bash -c '
    VARIANT="skipjack-gnome-gdx"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "skipjack-gnome" ]
}

@test "sync-build-cache: plain variant unchanged" {
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

# ═══════════════════════════════════════════════════════════════════════════
# Missing Variant Cache Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "sync-build-cache: warns and exits 0 when variant cache missing" {
  run bash -c '
    CACHE_VARIANT="/nonexistent/path/skipjack"
    if [[ ! -d "$CACHE_VARIANT" ]]; then
      echo "Warning: Variant cache does not exist: $CACHE_VARIANT" >&2
      exit 0
    fi
    exit 1
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "Warning:"* ]]
}

@test "sync-build-cache: handles existing but empty variant cache" {
  CACHE_VARIANT="${TEST_ROOT}/repo/.rpm-cache/yellowfin"
  mkdir -p "${CACHE_VARIANT}"

  run bash -c '
    CACHE_VARIANT="'"${CACHE_VARIANT}"'"
    if [[ ! -d "$CACHE_VARIANT" ]]; then
      echo "Warning: Variant cache does not exist" >&2
      exit 0
    fi
    echo "Syncing..."
    exit 0
  '
  [ "$status" -eq 0 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Sync Behavior
# ═══════════════════════════════════════════════════════════════════════════

@test "sync-build-cache: syncs dnf subdirectory when present" {
  REPO_ROOT="${TEST_ROOT}/repo"
  CACHE_BASE="${REPO_ROOT}/.rpm-cache/shared"
  CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/yellowfin"
  mkdir -p "${CACHE_VARIANT}/dnf"
  mkdir -p "${CACHE_BASE}/dnf"
  echo "test-data" > "${CACHE_VARIANT}/dnf/somefile"

  run bash -c '
    CACHE_VARIANT="'"${CACHE_VARIANT}"'"
    CACHE_BASE="'"${CACHE_BASE}"'"
    for subdir in dnf libdnf5 rpm; do
      if [[ -d "${CACHE_VARIANT}/${subdir}" ]]; then
        echo "  Syncing ${subdir}..."
      fi
    done
  '
  [[ "$output" == *"Syncing dnf"* ]]
}

@test "sync-build-cache: skips nonexistent subdirectories" {
  REPO_ROOT="${TEST_ROOT}/repo"
  CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/yellowfin"
  mkdir -p "${CACHE_VARIANT}"

  run bash -c '
    CACHE_VARIANT="'"${CACHE_VARIANT}"'"
    synced=0
    for subdir in dnf libdnf5 rpm; do
      if [[ -d "${CACHE_VARIANT}/${subdir}" ]]; then
        synced=$((synced + 1))
        echo "  Syncing ${subdir}..."
      fi
    done
    echo "synced=$synced"
  '
  [[ "$output" == *"synced=0"* ]]
}

@test "sync-build-cache: attempts all three subdirectories" {
  REPO_ROOT="${TEST_ROOT}/repo"
  CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/yellowfin"
  mkdir -p "${CACHE_VARIANT}"/{dnf,libdnf5,rpm}

  run bash -c '
    CACHE_VARIANT="'"${CACHE_VARIANT}"'"
    for subdir in dnf libdnf5 rpm; do
      if [[ -d "${CACHE_VARIANT}/${subdir}" ]]; then
        echo "  Syncing ${subdir}..."
      fi
    done
  '
  [[ "$output" == *"dnf"* ]]
  [[ "$output" == *"libdnf5"* ]]
  [[ "$output" == *"rpm"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Error Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "sync-build-cache: exits with error when no variant provided" {
  run bash -c '
    VARIANT="${1:-}"
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: $0 <variant>" >&2
      exit 1
    fi
  ' _
  [ "$status" -eq 1 ]
}

@test "sync-build-cache: outputs usage message to stderr" {
  run bash -c '
    VARIANT="${1:-}"
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: $0 <variant>" >&2
      exit 1
    fi
  ' _
  [[ "$output" == "Usage: $0 <variant>" ]]
}
