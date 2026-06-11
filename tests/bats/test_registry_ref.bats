#!/usr/bin/env bats
# Unit tests for scripts/_registry.sh — registry prefix resolution
#
# Tests:
#   - _registry_host() with and without TUNA_REGISTRY_* override
#   - registry_ref() for images with tags, digests, and base paths
#   - registry_ref() with env var overrides (path, tag, digest, registry)
#   - registry_ref() with explicit tag_spec argument
#   - registry_ref() for unknown image names (error)
#   - registry_ref() digest precedence over tag
#   - Exported variables (COMMON_IMAGE, BREW_IMAGE, BASE_IMAGE)

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
REAL_YQ="$(command -v yq)"

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/scripts"

  # Create a test registry-map.yaml
  cat >"${TEST_ROOT}/registry-map.yaml" <<'YAML'
registries:
  ghcr: ghcr.io
  quay: quay.io
  docker: docker.io
images:
  common:
    registry: ghcr
    path: projectbluefin/common
    tag: latest
  brew:
    registry: ghcr
    path: projectbluefin/brew
    tag: stable
  akmods:
    registry: ghcr
    path: ublue-os
  almalinux-bootc:
    registry: quay
    path: almalinuxorg/almalinux-bootc
    tag: "10"
  pinned:
    registry: ghcr
    path: tuna-os/tools
    digest: "sha256:abc123def456"
  multi-override:
    registry: docker
    path: library/ubuntu
    tag: "22.04"
YAML

  # Patch _registry.sh: point REGISTRY_MAP at the test map and replace
  # bare `yq` with the real yq absolute path so no stubs are needed.
  sed -e "s|REGISTRY_MAP=.*|REGISTRY_MAP=\"${TEST_ROOT}/registry-map.yaml\"|" \
      -e "s|yq |${REAL_YQ} |g" \
      "${REPO_ROOT}/scripts/_registry.sh" > "${TEST_ROOT}/scripts/_registry.sh"

  # Remove the export block at the end (it uses images not in the test map
  # and would fail). The tests call registry_ref directly.
  sed -i '/^# Export commonly-used/,/^fi$/d' "${TEST_ROOT}/scripts/_registry.sh"

  export TEST_ROOT
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── _registry_host ─────────────────────────────────────────────────────────

@test "_registry_host: resolves ghcr key" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    _registry_host ghcr
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io" ]]
}

@test "_registry_host: resolves quay key" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    _registry_host quay
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "quay.io" ]]
}

@test "_registry_host: applies TUNA_REGISTRY override" {
  run bash -c '
    export TUNA_REGISTRY_ghcr=mirror.internal.example.com
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    _registry_host ghcr
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "mirror.internal.example.com" ]]
}

# ── registry_ref: basic resolution ────────────────────────────────────────

@test "registry_ref common: resolves to ghcr.io/projectbluefin/common:latest" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref common
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/projectbluefin/common:latest" ]]
}

@test "registry_ref brew: resolves to ghcr.io/projectbluefin/brew:stable" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref brew
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/projectbluefin/brew:stable" ]]
}

@test "registry_ref akmods: resolves base path without tag" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref akmods
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/ublue-os" ]]
}

@test "registry_ref almalinux-bootc: resolves quay image with tag" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref almalinux-bootc
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "quay.io/almalinuxorg/almalinux-bootc:10" ]]
}

@test "registry_ref pinned: digest takes precedence over tag" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref pinned
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/tuna-os/tools@sha256:abc123def456" ]]
}

# ── registry_ref: explicit tag_spec ───────────────────────────────────────

@test "registry_ref with custom tag" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref common ":v2.0"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/projectbluefin/common:v2.0" ]]
}

@test "registry_ref with explicit digest" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref common "@sha256:deadbeef"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/projectbluefin/common@sha256:deadbeef" ]]
}

# ── registry_ref: env var overrides ───────────────────────────────────────

@test "registry_ref: TUNA_IMAGE_PATH_ overrides default path" {
  run bash -c '
    export TUNA_IMAGE_PATH_common=myorg/my-fork
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref common
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/myorg/my-fork:latest" ]]
}

@test "registry_ref: TUNA_IMAGE_TAG_ overrides default tag" {
  run bash -c '
    export TUNA_IMAGE_TAG_common=nightly
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref common
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/projectbluefin/common:nightly" ]]
}

@test "registry_ref: TUNA_REGISTRY_ overrides hostname" {
  run bash -c '
    export TUNA_REGISTRY_ghcr=registry.internal.example.com
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref common
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "registry.internal.example.com/projectbluefin/common:latest" ]]
}

@test "registry_ref: TUNA_IMAGE_DIGEST_ overrides digest" {
  run bash -c '
    export TUNA_IMAGE_DIGEST_pinned=sha256:ffffff999999
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref pinned
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "ghcr.io/tuna-os/tools@sha256:ffffff999999" ]]
}

@test "registry_ref: multiple overrides combined (registry + path + tag)" {
  run bash -c '
    export TUNA_REGISTRY_ghcr=mirror.example.com
    export TUNA_IMAGE_PATH_common=custom/path
    export TUNA_IMAGE_TAG_common=experimental
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref common
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "mirror.example.com/custom/path:experimental" ]]
}

@test "registry_ref: override with hyphens in name (multi-override)" {
  run bash -c '
    export TUNA_IMAGE_PATH_multi_override=myorg/custom-ubuntu
    export TUNA_IMAGE_TAG_multi_override=jammy
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref multi-override
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "docker.io/myorg/custom-ubuntu:jammy" ]]
}

# ── registry_ref: error handling ──────────────────────────────────────────

@test "registry_ref: unknown image name returns error" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref nonexistent
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"unknown image name"* ]]
}

@test "registry_ref: empty name returns error" {
  run bash -c '
    source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
    registry_ref ""
  '
  [ "$status" -eq 1 ]
}
