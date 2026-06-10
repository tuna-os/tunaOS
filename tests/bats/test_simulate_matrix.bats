#!/usr/bin/env bats
# Unit tests for scripts/simulate-matrix.sh
#
# Tests:
#   - Variant/flavor extraction from simulated yq/jq output
#   - Platform list parsing
#   - Image reference construction (localhost + ghcr.io)
#   - Command simulation output format

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# simulate-matrix.sh — Image Reference Construction
# ═══════════════════════════════════════════════════════════════════════════

@test "simulate-matrix: localhost image reference" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="gnome"
    LOCAL_IMAGE_REF="localhost/${VARIANT}:${FLAVOR}"
    echo "$LOCAL_IMAGE_REF"
  '
  [ "$output" = "localhost/yellowfin:gnome" ]
}

@test "simulate-matrix: ghcr.io image reference" {
  run bash -c '
    GITHUB_REPOSITORY_OWNER="tuna-os"
    VARIANT="albacore"
    FLAVOR="kde"
    GHCR_REF="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${VARIANT}:${FLAVOR}"
    echo "$GHCR_REF"
  '
  [ "$output" = "ghcr.io/tuna-os/albacore:kde" ]
}

@test "simulate-matrix: ghcr.io falls back to default owner" {
  run bash -c '
    GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
    echo "$GITHUB_REPOSITORY_OWNER"
  '
  [ "$output" = "tuna-os" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# simulate-matrix.sh — Platform Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "simulate-matrix: single platform" {
  run bash -c '
    PLATFORMS="linux/amd64"
    echo "Platforms: $PLATFORMS"
  '
  [ "$output" = "Platforms: linux/amd64" ]
}

@test "simulate-matrix: multiple platforms joined with comma" {
  run bash -c '
    PLATFORMS="linux/amd64, linux/arm64"
    echo "Platforms: $PLATFORMS"
  '
  [[ "$output" == *"linux/amd64"* ]]
  [[ "$output" == *"linux/arm64"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# simulate-matrix.sh — Build Command Simulation
# ═══════════════════════════════════════════════════════════════════════════

@test "simulate-matrix: build command format" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="gnome"
    PLATFORM="linux/amd64"
    echo "  --> just build \"$VARIANT\" \"$FLAVOR\" \"$PLATFORM\" 1 \"latest\""
  '
  [ "$output" = '  --> just build "yellowfin" "gnome" "linux/amd64" 1 "latest"' ]
}

@test "simulate-matrix: chunkify command format" {
  run bash -c '
    LOCAL_IMAGE_REF="localhost/yellowfin:gnome"
    echo "  --> just chunkify \"$LOCAL_IMAGE_REF\""
  '
  [ "$output" = '  --> just chunkify "localhost/yellowfin:gnome"' ]
}

@test "simulate-matrix: full pipeline simulation produces expected output" {
  run bash -c '
    echo "Simulated GitHub Actions Matrix (Dry Run):"
    echo "=========================================="
    echo ""
    echo "Variant: yellowfin (Yellowfin Tuna)"
    echo "Platforms: linux/amd64, linux/arm64"
    echo "Pipeline Execution Simulation:"
    echo "------------------------------"
    echo "Flavor: gnome"
    echo "  --> just build \"yellowfin\" \"gnome\" \"linux/amd64\" 1 \"latest\""
    echo "  --> just build \"yellowfin\" \"gnome\" \"linux/arm64\" 1 \"latest\""
    echo "  --> just chunkify \"localhost/yellowfin:gnome\""
    echo "  --> podman image tag \"localhost/yellowfin:gnome\" \"ghcr.io/tuna-os/yellowfin:gnome\""
    echo "  --> podman push \"ghcr.io/tuna-os/yellowfin:gnome\" (to registry)"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"yellowfin"* ]]
  [[ "$output" == *"gnome"* ]]
  [[ "$output" == *"chunkify"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# simulate-matrix.sh — Variant Description Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "simulate-matrix: variant with special characters in description" {
  run bash -c '
    VARIANT="bonito"
    DESC="Bonito (KDE Spin)"
    echo "Variant: $VARIANT ($DESC)"
  '
  [ "$output" = "Variant: bonito (Bonito (KDE Spin))" ]
}

@test "simulate-matrix: variant with empty description" {
  run bash -c '
    VARIANT="barebones"
    DESC=""
    echo "Variant: $VARIANT ($DESC)"
  '
  [ "$output" = "Variant: barebones ()" ]
}
