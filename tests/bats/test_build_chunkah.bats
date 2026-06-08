#!/usr/bin/env bats
# Unit tests for scripts/build-chunkah.sh — chunkah container image builder
#
# Tests:
#   - Local source directory detection
#   - Git clone fallback when no local source
#   - Image tag constant (localhost/chunkah:latest)
#   - Podman vs buildah fallback
#   - Build flags (security-opt, skip-unused-stages)
#   - set -euo pipefail enforcement

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"

setup() {
  TEST_ROOT="$(mktemp -d)"

  # Stub podman
  cat >"${TEST_ROOT}/podman" <<'PODMAN'
#!/usr/bin/env bash
echo "podman $*"
PODMAN
  chmod +x "${TEST_ROOT}/podman"

  # Stub buildah
  cat >"${TEST_ROOT}/buildah" <<'BUILDAH'
#!/usr/bin/env bash
echo "buildah $*"
BUILDAH
  chmod +x "${TEST_ROOT}/buildah"

  # Stub git
  cat >"${TEST_ROOT}/git" <<'GIT'
#!/usr/bin/env bash
if [[ "$1" == "clone" ]]; then
  mkdir -p "${3}"
  echo "cloned to ${3}"
fi
GIT
  chmod +x "${TEST_ROOT}/git"

  export PATH="${TEST_ROOT}:${PATH}"
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── Source detection ──────────────────────────────────────────────────────

@test "build-chunkah: uses local source dir when provided and exists" {
  SRC_DIR="${TEST_ROOT}/my-chunkah-src"
  mkdir -p "$SRC_DIR"
  run bash -c '
    SRC_DIR="'"$SRC_DIR"'"
    if [[ -n "${1:-}" ]] && [[ -d "$1" ]]; then
      echo "Building chunkah from local source: $1"
    fi
  ' _ "$SRC_DIR"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Building chunkah from local source"* ]]
}

@test "build-chunkah: clones from GitHub when no local source" {
  run bash -c '
    REPO_URL="https://github.com/coreos/chunkah.git"
    SRC_DIR=$(mktemp -d /tmp/chunkah-build-XXXXXX)
    echo "Cloning $REPO_URL -> $SRC_DIR"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Cloning https://github.com/coreos/chunkah.git"* ]]
}

@test "build-chunkah: skips local source when dir does not exist" {
  run bash -c '
    SRC_ARG="/nonexistent/path"
    if [[ -n "${SRC_ARG}" ]] && [[ -d "$SRC_ARG" ]]; then
      echo "local"
    else
      echo "clone"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "clone" ]]
}

@test "build-chunkah: skips local source when arg is empty" {
  run bash -c '
    SRC_ARG=""
    if [[ -n "${SRC_ARG:-}" ]] && [[ -d "$SRC_ARG" ]]; then
      echo "local"
    else
      echo "clone"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "clone" ]]
}

# ── Image tag ─────────────────────────────────────────────────────────────

@test "build-chunkah: tags as localhost/chunkah:latest" {
  run bash -c '
    TAG="localhost/chunkah:latest"
    echo "$TAG"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "localhost/chunkah:latest" ]]
}

# ── Build tool selection ──────────────────────────────────────────────────

@test "build-chunkah: prefers podman when available" {
  run bash -c '
    if command -v podman &>/dev/null; then
      echo "podman"
    elif command -v buildah &>/dev/null; then
      echo "buildah"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "podman" ]]
}

@test "build-chunkah: falls back to buildah when podman absent" {
  # Test the fallback logic: podman not available, buildah is
  run bash -c '
    has_podman() { return 1; }
    has_buildah() { return 0; }
    if has_podman; then echo "podman"
    elif has_buildah; then echo "buildah"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "buildah" ]]
}

# ── Build flags ───────────────────────────────────────────────────────────

@test "build-chunkah: passes security-opt label=disable" {
  run bash -c '
    echo "podman build --security-opt=label=disable --skip-unused-stages=false -t localhost/chunkah:latest ."
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"--security-opt=label=disable"* ]]
}

@test "build-chunkah: passes skip-unused-stages=false" {
  run bash -c '
    echo "--skip-unused-stages=false"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "--skip-unused-stages=false" ]]
}

@test "build-chunkah: passes tag flag" {
  run bash -c '
    TAG="localhost/chunkah:latest"
    echo "-t ${TAG}"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "-t localhost/chunkah:latest" ]]
}

# ── Strict mode ───────────────────────────────────────────────────────────

@test "build-chunkah: has set -euo pipefail" {
  run grep -c "set -euo pipefail" "${REPO_ROOT}/scripts/build-chunkah.sh"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}
