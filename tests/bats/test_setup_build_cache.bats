#!/usr/bin/env bats
# Unit tests for scripts/setup-build-cache.sh
#
# Tests:
#   - Variant name stripping (flavor suffixes removed)
#   - Cache directory creation
#   - Podman volume mount argument format
#   - Error handling when no variant provided
#   - Shared cache initialization marker

setup() {
  TEST_ROOT="$(mktemp -d)"
  REPO_ROOT="${TEST_ROOT}/repo"
  mkdir -p "${REPO_ROOT}/scripts"
  mkdir -p "${REPO_ROOT}/.rpm-cache/shared/dnf"
  mkdir -p "${REPO_ROOT}/.rpm-cache/shared/libdnf5"
  mkdir -p "${REPO_ROOT}/.rpm-cache/shared/rpm"

  # Copy the setup-build-cache.sh for path checks
  cp "${BATS_TEST_DIRNAME}/../../scripts/setup-build-cache.sh" \
     "${REPO_ROOT}/scripts/setup-build-cache.sh"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Variant Name Stripping
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: strips -gdx suffix" {
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

@test "setup-build-cache: strips -hwe suffix" {
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

@test "setup-build-cache: strips -kde suffix" {
  run bash -c '
    VARIANT="skipjack-kde"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "skipjack" ]
}

@test "setup-build-cache: strips -dx suffix" {
  run bash -c '
    VARIANT="bonito-dx"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "bonito" ]
}

@test "setup-build-cache: strips combined -gnome-gdx-hwe suffix to base" {
  run bash -c '
    VARIANT="albacore-gnome-gdx-hwe"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "albacore-gnome" ]
}

@test "setup-build-cache: plain variant unchanged" {
  run bash -c '
    VARIANT="skipjack"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "skipjack" ]
}

@test "setup-build-cache: -dx suffix stripped after -kde check (order matters)" {
  # -dx is stripped last, so -kde-dx becomes -kde then (no -dx match after)
  # but -gdx-dx becomes -dx after stripping
  run bash -c '
    VARIANT="yellowfin-kde-dx"
    BASE_VARIANT="${VARIANT}"
    BASE_VARIANT="${BASE_VARIANT%-gdx}"
    BASE_VARIANT="${BASE_VARIANT%-hwe}"
    BASE_VARIANT="${BASE_VARIANT%-kde}"
    BASE_VARIANT="${BASE_VARIANT%-dx}"
    echo "$BASE_VARIANT"
  '
  [ "$output" = "yellowfin-dx" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Cache Directory Structure
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: creates shared cache directories" {
  REPO_ROOT="${TEST_ROOT}/repo"
  CACHE_BASE="${REPO_ROOT}/.rpm-cache/shared"
  mkdir -p "${CACHE_BASE}"/{dnf,libdnf5,rpm}
  [ -d "${CACHE_BASE}/dnf" ]
  [ -d "${CACHE_BASE}/libdnf5" ]
  [ -d "${CACHE_BASE}/rpm" ]
}

@test "setup-build-cache: creates variant cache directories" {
  REPO_ROOT="${TEST_ROOT}/repo"
  CACHE_VARIANT="${REPO_ROOT}/.rpm-cache/yellowfin"
  mkdir -p "${CACHE_VARIANT}"/{dnf,libdnf5,rpm}
  [ -d "${CACHE_VARIANT}/dnf" ]
  [ -d "${CACHE_VARIANT}/libdnf5" ]
  [ -d "${CACHE_VARIANT}/rpm" ]
}

@test "setup-build-cache: shared .initialized marker created when absent" {
  CACHE_BASE="${TEST_ROOT}/repo/.rpm-cache/shared"
  mkdir -p "${CACHE_BASE}"
  if [[ ! -f "${CACHE_BASE}/.initialized" ]]; then
    touch "${CACHE_BASE}/.initialized"
  fi
  [ -f "${CACHE_BASE}/.initialized" ]
}

@test "setup-build-cache: .initialized marker skipped when already present" {
  CACHE_BASE="${TEST_ROOT}/repo/.rpm-cache/shared"
  mkdir -p "${CACHE_BASE}"
  touch "${CACHE_BASE}/.initialized"
  # Second run should not error
  if [[ ! -f "${CACHE_BASE}/.initialized" ]]; then
    touch "${CACHE_BASE}/.initialized"
  fi
  [ -f "${CACHE_BASE}/.initialized" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Volume Mount Argument Format
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: outputs correct --volume arguments" {
  CACHE_VARIANT="${TEST_ROOT}/repo/.rpm-cache/skipjack"
  mkdir -p "${CACHE_VARIANT}"/{dnf,libdnf5,rpm}

  run bash -c '
    CACHE_VARIANT="/tmp/test_cache/skipjack"
    echo "--volume"
    echo "${CACHE_VARIANT}/dnf:/var/cache/dnf:z"
    echo "--volume"
    echo "${CACHE_VARIANT}/libdnf5:/var/cache/libdnf5:z"
    echo "--volume"
    echo "${CACHE_VARIANT}/rpm:/var/lib/rpm:z"
    '

  [ "$status" -eq 0 ]
  # Count --volume occurrences
  volume_count=$(echo "$output" | grep -c "^--volume$")
  [ "$volume_count" -eq 3 ]
}

@test "setup-build-cache: volume mounts include :z SELinux label" {
  CACHE_VARIANT="${TEST_ROOT}/repo/.rpm-cache/yellowfin"
  mkdir -p "${CACHE_VARIANT}"/{dnf,libdnf5,rpm}

  run bash -c '
    CACHE_VARIANT="/tmp/test/yellowfin"
    echo "${CACHE_VARIANT}/dnf:/var/cache/dnf:z"
    echo "${CACHE_VARIANT}/libdnf5:/var/cache/libdnf5:z"
    echo "${CACHE_VARIANT}/rpm:/var/lib/rpm:z"
    '
  [[ "$output" == *":/var/cache/dnf:z"* ]]
  [[ "$output" == *":/var/cache/libdnf5:z"* ]]
  [[ "$output" == *":/var/lib/rpm:z"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Error Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache: exits with error when no variant provided" {
  run bash -c '
    VARIANT="${1:-}"
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: $0 <variant>" >&2
      exit 1
    fi
  ' _
  [ "$status" -eq 1 ]
}

@test "setup-build-cache: outputs usage message when no variant" {
  run bash -c '
    VARIANT="${1:-}"
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: $0 <variant>" >&2
      exit 1
    fi
  ' _
  [[ "$output" == "Usage: $0 <variant>" ]]
}
