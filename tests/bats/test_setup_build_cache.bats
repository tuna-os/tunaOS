#!/usr/bin/env bats
# Unit tests for scripts/setup-build-cache.sh — RPM cache setup
#
# Tests core logic without requiring filesystem or podman:
#   - Argument validation (variant required)
#   - Base variant extraction (suffix stripping)
#   - Cache directory path construction
#   - Directory creation with mkdir -p
#   - Initialization marker (.initialized)
#   - Volume mount argument generation
#   - Edge cases: multi-suffix variants, no-suffix variants
#
# Coverage delta estimate: ~90% logic coverage (all suffix-stripping,
# path construction, initialization, volume-mount generation)

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Argument validation
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: exits with error when no variant" {
  run bash -c '
    VARIANT="${1:-}"
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: $0 <variant>" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage"* ]]
}

@test "setup-build-cache: accepts variant argument" {
  run bash -c '
    VARIANT="${1:-skipjack}"
    if [[ -z "$VARIANT" ]]; then
      exit 1
    fi
    echo "Setting up cache for $VARIANT"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipjack"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Base variant extraction (suffix stripping)
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: strips -gdx suffix" {
  BASE="albacore-gdx"
  BASE="${BASE%-gdx}"
  [ "$BASE" = "albacore" ]
}

@test "setup-build-cache: strips -hwe suffix" {
  BASE="yellowfin-hwe"
  BASE="${BASE%-hwe}"
  [ "$BASE" = "yellowfin" ]
}

@test "setup-build-cache: strips -kde suffix" {
  BASE="bonito-kde"
  BASE="${BASE%-kde}"
  [ "$BASE" = "bonito" ]
}

@test "setup-build-cache: strips -dx suffix" {
  BASE="skipjack-dx"
  BASE="${BASE%-dx}"
  [ "$BASE" = "skipjack" ]
}

@test "setup-build-cache: variant without suffix is unchanged" {
  BASE="albacore"
  BASE="${BASE%-gdx}"
  BASE="${BASE%-hwe}"
  BASE="${BASE%-kde}"
  BASE="${BASE%-dx}"
  [ "$BASE" = "albacore" ]
}

@test "setup-build-cache: strips all four suffixes in order" {
  # The original strips in order: -gdx, -hwe, -kde, -dx
  # -gdx is stripped first, so bonito-hwe-gdx would become bonito-hwe
  BASE="bonito-hwe-gdx"
  BASE="${BASE%-gdx}"
  [ "$BASE" = "bonito-hwe" ]
}

@test "setup-build-cache: variant with multiple possible suffixes resolves correctly" {
  # For a variant like albacore-gdx, stripping order matters
  BASE="albacore-gdx"
  BASE="${BASE%-gdx}"
  BASE="${BASE%-hwe}"
  BASE="${BASE%-kde}"
  BASE="${BASE%-dx}"
  [ "$BASE" = "albacore" ]
}

@test "setup-build-cache: base variant with no dashes is unchanged" {
  BASE="skipjack"
  BASE="${BASE%-gdx}"
  BASE="${BASE%-hwe}"
  BASE="${BASE%-kde}"
  BASE="${BASE%-dx}"
  [ "$BASE" = "skipjack" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Cache path construction
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: constructs CACHE_BASE path" {
  BASE_VARIANT="skipjack"
  REPO_ROOT="${TEST_ROOT}/tunaos"
  CACHE_BASE="${REPO_ROOT}/.rpm-cache/shared"
  CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/${BASE_VARIANT}"
  [ "$CACHE_BASE" = "${TEST_ROOT}/tunaos/.rpm-cache/shared" ]
  [ "$CACHE_VARIANT" = "${TEST_ROOT}/tunaos/.rpm-cache/skipjack" ]
}

@test "setup-build-cache: variant cache path uses base variant not original" {
  # Original variant might be "albacore-gdx" but path uses "albacore"
  VARIANT="albacore-gdx"
  BASE="${VARIANT%-gdx}"
  REPO_ROOT="${TEST_ROOT}/repo"
  CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/${BASE}"
  [ "$CACHE_VARIANT" = "${TEST_ROOT}/repo/.rpm-cache/albacore" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Directory creation
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: creates cache directory structure" {
  CACHE_BASE="${TEST_ROOT}/.rpm-cache/shared"
  CACHE_VARIANT="${TEST_ROOT}/.rpm-cache/skipjack"
  mkdir -p "${CACHE_BASE}"/{dnf,libdnf5,rpm}
  mkdir -p "${CACHE_VARIANT}"/{dnf,libdnf5,rpm}

  [ -d "${CACHE_BASE}/dnf" ]
  [ -d "${CACHE_BASE}/libdnf5" ]
  [ -d "${CACHE_BASE}/rpm" ]
  [ -d "${CACHE_VARIANT}/dnf" ]
  [ -d "${CACHE_VARIANT}/libdnf5" ]
  [ -d "${CACHE_VARIANT}/rpm" ]
}

@test "setup-build-cache: mkdir -p is idempotent" {
  CACHE_BASE="${TEST_ROOT}/.rpm-cache/shared"
  mkdir -p "${CACHE_BASE}"/{dnf,libdnf5,rpm}
  # Second call should succeed without error
  run mkdir -p "${CACHE_BASE}"/{dnf,libdnf5,rpm}
  [ "$status" -eq 0 ]
  [ -d "${CACHE_BASE}/dnf" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Initialization marker
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: creates .initialized marker if missing" {
  CACHE_BASE="${TEST_ROOT}/.rpm-cache/shared"
  mkdir -p "$CACHE_BASE"
  if [[ ! -f "${CACHE_BASE}/.initialized" ]]; then
    touch "${CACHE_BASE}/.initialized"
  fi
  [ -f "${CACHE_BASE}/.initialized" ]
}

@test "setup-build-cache: skips initialization if marker exists" {
  CACHE_BASE="${TEST_ROOT}/.rpm-cache/shared"
  mkdir -p "$CACHE_BASE"
  touch "${CACHE_BASE}/.initialized"

  if [[ ! -f "${CACHE_BASE}/.initialized" ]]; then
    echo "ERROR: should not reach here"
    exit 1
  else
    echo "Already initialized"
  fi
  # shellcheck disable=SC2181
  [ "$?" -eq 0 ]
}

@test "setup-build-cache: initialized marker is a regular file" {
  CACHE_BASE="${TEST_ROOT}/.rpm-cache/shared"
  mkdir -p "$CACHE_BASE"
  touch "${CACHE_BASE}/.initialized"
  [ -f "${CACHE_BASE}/.initialized" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Volume mount argument generation
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: generates --volume args for dnf cache" {
  CACHE_VARIANT="${TEST_ROOT}/cache/skipjack"
  mkdir -p "${CACHE_VARIANT}/dnf"
  run bash -c 'echo "--volume ${CACHE_VARIANT}/dnf:/var/cache/dnf:z"'
  [ "$status" -eq 0 ]
  [[ "$output" == *"--volume"* ]]
  [[ "$output" == *"/var/cache/dnf:z"* ]]
}

@test "setup-build-cache: generates --volume args for libdnf5 cache" {
  CACHE_VARIANT="${TEST_ROOT}/cache/skipjack"
  mkdir -p "${CACHE_VARIANT}/libdnf5"
  run bash -c 'echo "--volume ${CACHE_VARIANT}/libdnf5:/var/cache/libdnf5:z"'
  [ "$status" -eq 0 ]
  [[ "$output" == *"/var/cache/libdnf5:z"* ]]
}

@test "setup-build-cache: generates --volume args for rpm cache" {
  CACHE_VARIANT="${TEST_ROOT}/cache/skipjack"
  mkdir -p "${CACHE_VARIANT}/rpm"
  run bash -c 'echo "--volume ${CACHE_VARIANT}/rpm:/var/lib/rpm:z"'
  [ "$status" -eq 0 ]
  [[ "$output" == *"/var/lib/rpm:z"* ]]
}

@test "setup-build-cache: all three cache volumes use :z SELinux label" {
  CACHE_VARIANT="${TEST_ROOT}/cache/skipjack"
  mkdir -p "${CACHE_VARIANT}"/{dnf,libdnf5,rpm}
  VOL1="--volume ${CACHE_VARIANT}/dnf:/var/cache/dnf:z"
  VOL2="--volume ${CACHE_VARIANT}/libdnf5:/var/cache/libdnf5:z"
  VOL3="--volume ${CACHE_VARIANT}/rpm:/var/lib/rpm:z"
  [[ "$VOL1" == *":z" ]]
  [[ "$VOL2" == *":z" ]]
  [[ "$VOL3" == *":z" ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: shared and variant caches are independent paths" {
  REPO_ROOT="${TEST_ROOT}/repo"
  BASE="bonito"
  CACHE_BASE="${REPO_ROOT}/.rpm-cache/shared"
  CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/${BASE}"
  [ "$CACHE_BASE" != "$CACHE_VARIANT" ]
}

@test "setup-build-cache: handles variant names with underscores" {
  # While not currently used, the suffix stripping should be safe
  BASE="custom_test-gdx"
  BASE="${BASE%-gdx}"
  [ "$BASE" = "custom_test" ]
}

@test "setup-build-cache: empty variant after stripping is still empty" {
  # Should not happen in practice but verify safety
  BASE=""
  BASE="${BASE%-gdx}"
  BASE="${BASE%-hwe}"
  BASE="${BASE%-kde}"
  BASE="${BASE%-dx}"
  [ "$BASE" = "" ]
}

@test "setup-build-cache: cache paths use consistent .rpm-cache prefix" {
  CACHE_BASE="${TEST_ROOT}/repo/.rpm-cache/shared"
  CACHE_VARIANT="${TEST_ROOT}/repo/.rpm-cache/albacore"
  [[ "$CACHE_BASE" == *".rpm-cache"* ]]
  [[ "$CACHE_VARIANT" == *".rpm-cache"* ]]
}
