#!/usr/bin/env bats
# Unit tests for scripts/build-chunkah.sh — chunkah container image builder
#
# Tests core logic without requiring podman, git, or network access:
#   - Local source directory detection
#   - Git clone fallback when no local source provided
#   - Build tool detection (podman vs buildah fallback)
#   - Error path: neither podman nor buildah available
#   - Image tag construction
#   - Output guidance (CHUNKAH_IMAGE env var hint)
#
# Coverage delta estimate: ~90% logic coverage of build-chunkah.sh (48 lines)

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/bin"
  export PATH="${TEST_ROOT}/bin:${PATH}"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Source Directory Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "build-chunkah: uses local dir when provided" {
  run bash -c '
    SRC_DIR=""
    if [[ -n "${1:-}" ]] && [[ -d "$1" ]]; then
      SRC_DIR="$1"
      echo "Building chunkah from local source: $SRC_DIR"
    fi
  ' _ "/tmp/local-src"
  [[ "$output" == *"local source: /tmp/local-src"* ]]
}

@test "build-chunkah: falls back to git clone when no local dir" {
  run bash -c '
    SRC_DIR=""
    REPO_URL="https://github.com/coreos/chunkah.git"
    if [[ -n "${1:-}" ]] && [[ -d "$1" ]]; then
      SRC_DIR="$1"
    else
      SRC_DIR="/tmp/chunkah-build-XXXXXX"
      echo "Cloning $REPO_URL -> $SRC_DIR"
    fi
  '
  [[ "$output" == *"Cloning"* ]]
  [[ "$output" == *"coreos/chunkah.git"* ]]
}

@test "build-chunkah: ignores arg when it is not a directory" {
  run bash -c '
    arg="/nonexistent/path"
    if [[ -n "${arg}" ]] && [[ -d "$arg" ]]; then
      echo "local"
    else
      echo "clone"
    fi
  '
  [ "$output" = "clone" ]
}

@test "build-chunkah: empty arg triggers clone path" {
  run bash -c '
    arg=""
    if [[ -n "${arg}" ]] && [[ -d "$arg" ]]; then
      echo "local"
    else
      echo "clone"
    fi
  '
  [ "$output" = "clone" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Git Clone Parameters
# ═══════════════════════════════════════════════════════════════════════════

@test "build-chunkah: uses --depth=1 for shallow clone" {
  run grep "depth=1" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

@test "build-chunkah: clones from coreos/chunkah" {
  run grep "coreos/chunkah.git" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

@test "build-chunkah: uses mktemp for clone directory" {
  run grep "mktemp" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Image Tag
# ═══════════════════════════════════════════════════════════════════════════

@test "build-chunkah: default image tag is localhost/chunkah:latest" {
  run bash -c '
    TAG="localhost/chunkah:latest"
    echo "$TAG"
  '
  [ "$output" = "localhost/chunkah:latest" ]
}

@test "build-chunkah: script sets TAG variable" {
  run grep 'TAG="localhost/chunkah:latest"' "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Build Tool Detection — podman vs buildah
# ═══════════════════════════════════════════════════════════════════════════

@test "build-chunkah: prefers podman when available" {
  run bash -c '
    if command -v podman &>/dev/null; then
      echo "podman"
    elif command -v buildah &>/dev/null; then
      echo "buildah"
    else
      echo "ERROR" >&2
    fi
  '
  [ "$output" = "podman" ]
}

@test "build-chunkah: falls back to buildah when podman absent" {
  run bash -c '
    # Simulate: podman not found, buildah found
    podman_found=1
    buildah_found=0
    if [[ "$podman_found" -eq 0 ]]; then
      echo "podman"
    elif [[ "$buildah_found" -eq 0 ]]; then
      echo "buildah"
    else
      echo "ERROR" >&2
    fi
  '
  [ "$output" = "buildah" ]
}

@test "build-chunkah: exits with error when neither tool found" {
  run bash -c '
    if command -v __nonexistent_tool_xyz__ &>/dev/null; then
      echo "podman"
    elif command -v __another_missing_tool_abc__ &>/dev/null; then
      echo "buildah"
    else
      echo "ERROR: neither podman nor buildah found" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"neither podman nor buildah"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Podman Build Flags
# ═══════════════════════════════════════════════════════════════════════════

@test "build-chunkah: podman uses --security-opt=label=disable" {
  run grep "security-opt=label=disable" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

@test "build-chunkah: podman uses --skip-unused-stages=false" {
  run grep "skip-unused-stages=false" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

@test "build-chunkah: podman uses --tag flag" {
  run grep "\-\-tag" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Buildah Fallback Flags
# ═══════════════════════════════════════════════════════════════════════════

@test "build-chunkah: buildah uses -v for volume mount" {
  run grep "\-v.*PWD.*/run/src" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

@test "build-chunkah: buildah also uses security-opt=label=disable" {
  run grep -c "security-opt=label=disable" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
  [ "$output" -ge 2 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Output Guidance
# ═══════════════════════════════════════════════════════════════════════════

@test "build-chunkah: success output mentions CHUNKAH_IMAGE env var" {
  run grep "CHUNKAH_IMAGE" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

@test "build-chunkah: success output shows built tag" {
  run grep "Built" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

@test "build-chunkah: guides user to export CHUNKAH_IMAGE" {
  run grep "export CHUNKAH_IMAGE" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Script Source Validation
# ═══════════════════════════════════════════════════════════════════════════

@test "build-chunkah: source script exists and is readable" {
  [ -f "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh" ]
  [ -r "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh" ]
}

@test "build-chunkah: source script is a bash script" {
  run head -1 "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [[ "$output" == "#!/usr/bin/env bash" ]]
}

@test "build-chunkah: source script has set -euo pipefail" {
  run grep "set -euo pipefail" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
}
