#!/usr/bin/env bats
# Unit tests for scripts/published-image-ref.sh
#
# Exercises the real script against a fixture TUNAOS_BUILD_CONFIG rather
# than the live .github/build-config.yml, so these tests do not drift when
# variants are added/renamed there.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/scripts/published-image-ref.sh"
  TEST_ROOT="$(mktemp -d)"
  CONFIG="${TEST_ROOT}/build-config.yml"
  cat >"$CONFIG" <<'EOF'
variants:
  - id: plainvariant
    flavors: []
  - id: bonito-rawhide
    publish_name: bonito
    tag_suffix: rawhide
    flavors: []
EOF
  export TUNAOS_BUILD_CONFIG="$CONFIG"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

@test "published-image-ref: ghcr defaults to GITHUB_REPOSITORY_OWNER=tuna-os" {
  unset GITHUB_REPOSITORY_OWNER
  run bash "$SCRIPT" plainvariant gnome ghcr
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/tuna-os/plainvariant:gnome" ]
}

@test "published-image-ref: ghcr honors GITHUB_REPOSITORY_OWNER override" {
  GITHUB_REPOSITORY_OWNER=someorg run bash "$SCRIPT" plainvariant gnome ghcr
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/someorg/plainvariant:gnome" ]
}

@test "published-image-ref: repo argument defaults to ghcr when omitted" {
  unset GITHUB_REPOSITORY_OWNER
  run bash "$SCRIPT" plainvariant gnome
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/tuna-os/plainvariant:gnome" ]
}

@test "published-image-ref: local repo uses localhost/<variant-id>" {
  run bash "$SCRIPT" plainvariant gnome local
  [ "$status" -eq 0 ]
  # local intentionally keys off the raw variant id, not publish_name --
  # it addresses the image this host just built, before anything is pushed.
  [ "$output" = "localhost/plainvariant:gnome" ]
}

@test "published-image-ref: registry repo defaults host to localhost:5000" {
  unset REGISTRY
  run bash "$SCRIPT" plainvariant gnome registry
  [ "$status" -eq 0 ]
  [ "$output" = "localhost:5000/plainvariant:gnome" ]
}

@test "published-image-ref: registry repo honors REGISTRY override" {
  REGISTRY=example.com:443 run bash "$SCRIPT" plainvariant gnome registry
  [ "$status" -eq 0 ]
  [ "$output" = "example.com:443/plainvariant:gnome" ]
}

@test "published-image-ref: publish_name substitutes the variant id in the ref" {
  unset GITHUB_REPOSITORY_OWNER
  run bash "$SCRIPT" bonito-rawhide gnome ghcr
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/tuna-os/bonito:gnome-rawhide" ]
}

@test "published-image-ref: tag_suffix is not duplicated if already present" {
  unset GITHUB_REPOSITORY_OWNER
  run bash "$SCRIPT" bonito-rawhide gnome-rawhide ghcr
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/tuna-os/bonito:gnome-rawhide" ]
}

@test "published-image-ref: tag_suffix is inserted before a -testing suffix" {
  unset GITHUB_REPOSITORY_OWNER
  run bash "$SCRIPT" bonito-rawhide gnome-testing ghcr
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/tuna-os/bonito:gnome-rawhide-testing" ]
}

@test "published-image-ref: unknown variant fails with exit 1" {
  run bash "$SCRIPT" nonexistent gnome ghcr
  [ "$status" -eq 1 ]
  [[ "$output" == *"unknown variant: nonexistent"* ]]
}

@test "published-image-ref: unknown repo target fails with exit 1" {
  run bash "$SCRIPT" plainvariant gnome bogus
  [ "$status" -eq 1 ]
  [[ "$output" == *"unknown repo: bogus"* ]]
}

@test "published-image-ref: missing variant argument fails with usage error" {
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"usage: published-image-ref.sh"* ]]
}

@test "published-image-ref: missing tag argument fails" {
  run bash "$SCRIPT" plainvariant
  [ "$status" -ne 0 ]
}
