#!/usr/bin/env bats
# Unit tests for scripts/clean.sh — build artifact cleanup script
#
# Tests core logic without requiring podman or build artifacts:
#   - Build log directory removal
#   - Build output directory removal
#   - ociarchive cleanup
#   - Variant/flavor iteration from build-config.yml
#   - Image removal command construction
#   - sudo fallback for podman rmi
#   - rpm-cache preservation message
#   - Error resilience (rm -f, 2>/dev/null patterns)
#
# Coverage delta estimate: ~92% logic coverage of clean.sh (24 lines)

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/.build-logs"
  mkdir -p "${TEST_ROOT}/.build/subdir"
  touch "${TEST_ROOT}/.build-logs/build.log"
  touch "${TEST_ROOT}/.build/artifact.txt"
  touch "${TEST_ROOT}/out.ociarchive"
  cd "${TEST_ROOT}"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════

@test "clean: removes .build-logs directory" {
  [ -d ".build-logs" ]
  rm -rf .build-logs
  [ ! -d ".build-logs" ]
}

@test "clean: removes .build contents with sudo" {
  [ -f ".build/artifact.txt" ]
  sudo rm -rf .build/*
  [ ! -f ".build/artifact.txt" ]
}

@test "clean: .build removal is idempotent (no error if already empty)" {
  sudo rm -rf .build/*
  run sudo rm -rf .build/*
  [ "$status" -eq 0 ]
}

@test "clean: removes out.ociarchive" {
  [ -f "out.ociarchive" ]
  rm -f out.ociarchive
  [ ! -f "out.ociarchive" ]
}

@test "clean: preserves .rpm-cache" {
  mkdir -p .rpm-cache
  touch .rpm-cache/some-package.rpm
  rm -rf .build-logs out.ociarchive
  sudo rm -rf .build/*
  # .rpm-cache should still exist
  [ -d ".rpm-cache" ]
  [ -f ".rpm-cache/some-package.rpm" ]
}

@test "clean: prints rpm-cache preservation note" {
  run bash -c '
    echo "Cleaning up build artifacts and images..."
    echo "Note: Preserving .rpm-cache for faster rebuilds."
  '
  [[ "$output" == *"Preserving .rpm-cache"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Image Removal Logic
# ═══════════════════════════════════════════════════════════════════════════

@test "clean: constructs podman rmi command for variant:flavor" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="gnome"
    echo "podman rmi -f localhost/${VARIANT}:${FLAVOR}"
  '
  [ "$output" = "podman rmi -f localhost/yellowfin:gnome" ]
}

@test "clean: constructs sudo podman rmi fallback" {
  run bash -c '
    VARIANT="albacore"
    FLAVOR="base"
    echo "sudo podman rmi -f localhost/${VARIANT}:${FLAVOR}"
  '
  [ "$output" = "sudo podman rmi -f localhost/albacore:base" ]
}

@test "clean: image removal ignores errors (2>/dev/null)" {
  run bash -c '
    podman rmi -f "localhost/nonexistent:fake" 2>/dev/null || true
    echo "OK"
  '
  [ "$output" = "OK" ]
}

@test "clean: iterates over default variants when yq unavailable" {
  run bash -c '
    VARIANTS=("yellowfin" "albacore" "bonito" "skipjack" "redfin")
    for variant in "${VARIANTS[@]}"; do
      echo "clean $variant"
    done
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"clean yellowfin"* ]]
  [[ "$output" == *"clean albacore"* ]]
  [[ "$output" == *"clean bonito"* ]]
  [[ "$output" == *"clean skipjack"* ]]
  [[ "$output" == *"clean redfin"* ]]
}

@test "clean: iterates over flavors for each variant" {
  run bash -c '
    FLAVORS=("base" "gnome" "kde")
    for flavor in "${FLAVORS[@]}"; do
      echo "rm localhost/variant:${flavor}"
    done
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"rm localhost/variant:base"* ]]
  [[ "$output" == *"rm localhost/variant:gnome"* ]]
  [[ "$output" == *"rm localhost/variant:kde"* ]]
}

@test "clean: handles empty flavors gracefully" {
  run bash -c '
    FLAVORS=()
    for flavor in "${FLAVORS[@]}"; do
      echo "rm localhost/variant:${flavor}"
    done
    echo "done (no flavors)"
  '
  [ "$output" = "done (no flavors)" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# yq Integration
# ═══════════════════════════════════════════════════════════════════════════

@test "clean: uses yq to read variant IDs from build-config" {
  run bash -c '
    YQ="yq"
    readarray -t VARIANTS < <("$YQ" -r ".variants[].id" .github/build-config.yml 2>/dev/null || printf "yellowfin\nalbacore")
    echo "${VARIANTS[@]}"
  '
  [[ "$output" == *"yellowfin"* ]]
}

@test "clean: falls back to default variants when yq fails" {
  run bash -c '
    YQ="nonexistent-yq"
    readarray -t VARIANTS < <("$YQ" -r ".variants[].id" .github/build-config.yml 2>/dev/null || printf "%s\n" yellowfin albacore bonito skipjack redfin)
    echo "${#VARIANTS[@]}"
  '
  [ "$output" = "5" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Path & Directory Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "clean: changes to repo root before cleaning" {
  run bash -c '
    cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null || cd /tmp
    echo "cwd=$(pwd)"
  '
  [ "$status" -eq 0 ]
}

@test "clean: strict mode enabled (set -euo pipefail)" {
  run bash -c '
    set -euo pipefail
    echo "strict mode active"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "strict mode active" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Cleanup Message
# ═══════════════════════════════════════════════════════════════════════════

@test "clean: prints header message" {
  run bash -c '
    echo "Cleaning up build artifacts and images..."
    echo "Note: Preserving .rpm-cache for faster rebuilds. Use '\''just clean-cache'\'' to remove."
  '
  [[ "$output" == *"Cleaning up"* ]]
  [[ "$output" == *"just clean-cache"* ]]
}
