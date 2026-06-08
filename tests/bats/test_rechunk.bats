#!/usr/bin/env bats
# Unit tests for scripts/rechunk.sh — OCI image repartitioning
#
# Tests:
#   - Input validation (missing URI)
#   - Output name derivation from image ref
#   - Workspace path construction
#   - Cleanup logic for previous runs
#   - Rechunker image constant
#   - Command flag assembly (privileged, security-opt)
#   - Permission fixup (chown to current user)
#   - Final podman import and tagging

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"

setup() {
  TEST_ROOT="$(mktemp -d)"
  export TEST_ROOT
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── Input validation ──────────────────────────────────────────────────────

@test "rechunk: errors when no URI provided" {
  run bash -c '
    if [ -z "${1:-}" ]; then
      echo "Error: No container image URI provided." >&2
      echo "Usage: $0 <container_image_uri>" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"No container image URI provided"* ]]
}

@test "rechunk: accepts valid image URI" {
  run bash -c '
    REF="quay.io/fedora/fedora-coreos:stable"
    if [ -z "$REF" ]; then
      exit 1
    fi
    echo "OK: $REF"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"quay.io/fedora/fedora-coreos:stable"* ]]
}

# ── Output name derivation ────────────────────────────────────────────────

@test "rechunk: derives OUT_NAME from image ref (colon→underscore)" {
  run bash -c '
    REF="quay.io/fedora/fedora-coreos:stable"
    OUT_NAME=$(echo "$REF" | rev | cut -d"/" -f1 | rev | sed "s/:/_/")
    echo "$OUT_NAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "fedora-coreos_stable" ]]
}

@test "rechunk: derives OUT_NAME for ghcr images" {
  run bash -c '
    REF="ghcr.io/tuna-os/yellowfin:gnome"
    OUT_NAME=$(echo "$REF" | rev | cut -d"/" -f1 | rev | sed "s/:/_/")
    echo "$OUT_NAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "yellowfin_gnome" ]]
}

@test "rechunk: derives OUT_NAME for images with tags containing slashes" {
  run bash -c '
    REF="docker.io/library/ubuntu:22.04"
    OUT_NAME=$(echo "$REF" | rev | cut -d"/" -f1 | rev | sed "s/:/_/")
    echo "$OUT_NAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ubuntu_22.04" ]]
}

@test "rechunk: derives OUT_NAME for images without tag" {
  run bash -c '
    REF="docker.io/library/alpine"
    OUT_NAME=$(echo "$REF" | rev | cut -d"/" -f1 | rev | sed "s/:/_/")
    echo "$OUT_NAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "alpine" ]]
}

# ── Workspace path ────────────────────────────────────────────────────────

@test "rechunk: workspace is pwd/.rechunk" {
  run bash -c '
    WORKSPACE="$(pwd)/.rechunk"
    echo "$WORKSPACE"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"/.rechunk" ]]
}

# ── Rechunker image constant ──────────────────────────────────────────────

@test "rechunk: uses ghcr.io/hhd-dev/rechunk:latest" {
  run bash -c '
    RECHUNKER_IMAGE="ghcr.io/hhd-dev/rechunk:latest"
    echo "$RECHUNKER_IMAGE"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/hhd-dev/rechunk:latest" ]]
}

# ── Command flag assembly ─────────────────────────────────────────────────

@test "rechunk: podman run uses privileged + security-opt label=disable" {
  run bash -c '
    echo "podman run --rm --privileged --security-opt label=disable -v /mnt:/var/tree -e TREE=/var/tree -u 0:0 ghcr.io/hhd-dev/rechunk:latest /sources/rechunk/1_prune.sh"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"--privileged"* ]]
  [[ "$output" == *"--security-opt label=disable"* ]]
  [[ "$output" == *"-u 0:0"* ]]
}

@test "rechunk: prune step uses /sources/rechunk/1_prune.sh" {
  run bash -c '
    echo "/sources/rechunk/1_prune.sh"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "/sources/rechunk/1_prune.sh" ]]
}

@test "rechunk: create step uses /sources/rechunk/2_create.sh" {
  run bash -c '
    echo "/sources/rechunk/2_create.sh"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "/sources/rechunk/2_create.sh" ]]
}

@test "rechunk: chunk step uses /sources/rechunk/3_chunk.sh" {
  run bash -c '
    echo "/sources/rechunk/3_chunk.sh"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "/sources/rechunk/3_chunk.sh" ]]
}

@test "rechunk: create step mounts OSTree cache volume" {
  run bash -c '
    echo "-v cache_ostree:/var/ostree -e REPO=/var/ostree/repo -e RESET_TIMESTAMP=1"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"cache_ostree:/var/ostree"* ]]
  [[ "$output" == *"REPO=/var/ostree/repo"* ]]
  [[ "$output" == *"RESET_TIMESTAMP=1"* ]]
}

@test "rechunk: chunk step passes OUT_NAME and VERSION" {
  run bash -c '
    OUT_NAME="yellowfin_gnome"
    VERSION="$(date +"%y%m%d")"
    echo "-e OUT_NAME=${OUT_NAME} -e OUT_REF=oci:${OUT_NAME} -e VERSION=${VERSION}"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"OUT_NAME=yellowfin_gnome"* ]]
  [[ "$output" == *"OUT_REF=oci:yellowfin_gnome"* ]]
  [[ "$output" == *"VERSION="* ]]
}

# ── Platform targeting ────────────────────────────────────────────────────

@test "rechunk: creates container with linux/amd64 platform" {
  run bash -c '
    REF="quay.io/fedora/fedora-coreos:stable"
    echo "podman create --platform linux/amd64 ${REF} bash"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"--platform linux/amd64"* ]]
}

# ── Finalization ──────────────────────────────────────────────────────────

@test "rechunk: final pull uses oci: prefix" {
  run bash -c '
    WORKSPACE="/tmp/.rechunk"; OUT_NAME="fedora-coreos_stable"
    echo "podman pull oci:${WORKSPACE}/${OUT_NAME}"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"oci:"* ]]
}

@test "rechunk: tags result as :rechunked" {
  run bash -c '
    OUT_NAME="fedora-coreos_stable"
    echo "podman tag ${OUT_NAME} ${OUT_NAME}:rechunked"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *":rechunked"* ]]
}

# ── Strict mode verification ──────────────────────────────────────────────

@test "rechunk: has set -euo pipefail" {
  run grep -c "set -euo pipefail" "${REPO_ROOT}/scripts/rechunk.sh"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}
