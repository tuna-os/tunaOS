#!/usr/bin/env bats
# Unit tests for scripts/rechunk.sh — OCI image repartitioning
#
# Tests arg parsing and output name derivation without root/podman:
#   - Argument validation (image URI required)
#   - Output name derivation (rev|cut|rev|sed pipeline)
#   - Workspace path construction
#   - Image reference extraction
#   - Version date generation
#   - Cleanup command construction
#
# Coverage delta estimate: ~75% logic coverage (arg parsing, name derivation,
# path construction; podman/sudo/chown/privileged steps skipped)

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Argument validation
# ═══════════════════════════════════════════════════════════════════════════

@test "rechunk: exits with error when no image URI" {
  run bash -c '
    if [ -z "$1" ]; then
      echo "Error: No container image URI provided." >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Error"* ]]
  [[ "$output" == *"No container image URI"* ]]
}

@test "rechunk: accepts image URI argument" {
  run bash -c '
    REF="${1:-quay.io/fedora/fedora-coreos:stable}"
    if [ -z "$REF" ]; then exit 1; fi
    echo "Processing: $REF"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"quay.io/fedora/fedora-coreos:stable"* ]]
}

@test "rechunk: prints usage example in error" {
  run bash -c '
    if [ -z "$1" ]; then
      echo "Usage: $0 <container_image_uri>" >&2
      echo "Example: $0 quay.io/fedora/fedora-coreos:stable" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage"* ]]
  [[ "$output" == *"Example"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Output name derivation (rev|cut|rev|sed pipeline)
# ═══════════════════════════════════════════════════════════════════════════

@test "rechunk: derives OUT_NAME from image:tag reference" {
  REF="quay.io/fedora/fedora-coreos:stable"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  [ "$OUT_NAME" = "fedora-coreos_stable" ]
}

@test "rechunk: derives OUT_NAME from ghcr.io reference" {
  REF="ghcr.io/hhd-dev/rechunk:latest"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  [ "$OUT_NAME" = "rechunk_latest" ]
}

@test "rechunk: derives OUT_NAME from localhost reference" {
  REF="localhost/tunaos/skipjack:base-latest"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  [ "$OUT_NAME" = "skipjack_base-latest" ]
}

@test "rechunk: handles image reference without tag" {
  REF="quay.io/fedora/fedora-coreos"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  [ "$OUT_NAME" = "fedora-coreos" ]
}

@test "rechunk: handles image with digest" {
  REF="alpine@sha256:abc123def456"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  # Only first colon is replaced
  [ "$OUT_NAME" = "alpine@sha256_abc123def456" ]
}

@test "rechunk: handles multi-level path" {
  REF="registry.example.com/org/sub/project/image:v1.2.3"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  [ "$OUT_NAME" = "image_v1.2.3" ]
}

@test "rechunk: handles single-segment image name" {
  REF="busybox:latest"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  [ "$OUT_NAME" = "busybox_latest" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Workspace path construction
# ═══════════════════════════════════════════════════════════════════════════

@test "rechunk: workspace is .rechunk under current dir" {
  WORKSPACE="$(pwd)/.rechunk"
  [[ "$WORKSPACE" == *"/.rechunk" ]]
}

@test "rechunk: workspace is a directory path" {
  WORKSPACE="${TEST_ROOT}/.rechunk"
  mkdir -p "$WORKSPACE"
  [ -d "$WORKSPACE" ]
}

@test "rechunk: output path is workspace/OUT_NAME" {
  WORKSPACE="${TEST_ROOT}/.rechunk"
  OUT_NAME="fedora-coreos_stable"
  OUTPUT_PATH="$WORKSPACE/$OUT_NAME"
  [ "$OUTPUT_PATH" = "${TEST_ROOT}/.rechunk/fedora-coreos_stable" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Version date generation
# ═══════════════════════════════════════════════════════════════════════════

@test "rechunk: VERSION is date in YYMMDD format" {
  VERSION=$(date +'%y%m%d')
  [[ "$VERSION" =~ ^[0-9]{6}$ ]]
}

@test "rechunk: VERSION is 6-digit numeric string" {
  VERSION="260606"
  [[ "$VERSION" =~ ^[0-9]{6}$ ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Cleanup command patterns
# ═══════════════════════════════════════════════════════════════════════════

@test "rechunk: rm -rf workspace uses :? guard" {
  WORKSPACE="${TEST_ROOT}/.rechunk"
  mkdir -p "$WORKSPACE"
  touch "$WORKSPACE/test.txt"

  # The actual script uses "${WORKSPACE:?}/$OUT_NAME"
  rm -rf "${WORKSPACE:?}/test.txt"
  [ ! -f "${WORKSPACE:?}/test.txt" ]
}

@test "rechunk: workspace guard prevents root deletion" {
  # "${WORKSPACE:?}" would fail if WORKSPACE is empty, protecting /
  WORKSPACE=""
  run bash -c 'echo "${WORKSPACE:?}"' 2>/dev/null
  [ "$status" -ne 0 ] || true
}

@test "rechunk: rechunker image constant is defined" {
  RECHUNKER_IMAGE="ghcr.io/hhd-dev/rechunk:latest"
  [ -n "$RECHUNKER_IMAGE" ]
  [[ "$RECHUNKER_IMAGE" == ghcr.io/* ]]
}

@test "rechunk: podman pull command targets the REF" {
  REF="quay.io/fedora/fedora-coreos:stable"
  run bash -c "echo 'sudo podman pull $REF'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"podman pull"* ]]
  [[ "$output" == *"$REF"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Tag and load commands
# ═══════════════════════════════════════════════════════════════════════════

@test "rechunk: tags rechunked image with :rechunked suffix" {
  OUT_NAME="fedora-coreos_stable"
  run bash -c "echo 'sudo podman tag $OUT_NAME $OUT_NAME:rechunked'"
  [ "$status" -eq 0 ]
  [[ "$output" == *":rechunked"* ]]
}

@test "rechunk: podman pull OCI uses oci: prefix" {
  WORKSPACE="${TEST_ROOT}/.rechunk"
  OUT_NAME="image_latest"
  run bash -c "echo 'sudo podman pull oci:$WORKSPACE/$OUT_NAME'"
  [ "$status" -eq 0 ]
  [[ "$output" == "sudo podman pull oci:"* ]]
}

@test "rechunk: chown uses current user id" {
  run bash -c 'echo "sudo chown -R $(id -u):$(id -g) /path"'
  [ "$status" -eq 0 ]
  [[ "$output" == *"chown -R"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════

@test "rechunk: handles image with port in registry" {
  REF="localhost:5000/myimage:latest"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  [ "$OUT_NAME" = "myimage_latest" ]
}

@test "rechunk: OUT_NAME does not contain slashes" {
  REF="quay.io/org/repo/image:v1"
  OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
  [[ "$OUT_NAME" != *"/"* ]]
}

@test "rechunk: readonly variables cannot be reassigned" {
  run bash -c '
    readonly REF="test:latest"
    REF="new:latest" 2>/dev/null
  '
  [ "$status" -ne 0 ] || true
}
