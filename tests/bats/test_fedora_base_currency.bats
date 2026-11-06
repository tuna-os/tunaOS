#!/usr/bin/env bats
# Base-version pins that must move together (tunaOS#1171).
#
# docs/FEDORA-BASE-POLICY.md commits the project to tracking one Fedora stable at a
# time. Executing that commitment means bumping a base version in several
# places at once, and this repo has already been bitten by exactly that:
# get-base-image.sh's header records a second hardcoded copy of the
# variant→base map drifting from build-config.yml —
#
#   bonito    build-config: fedora-bootc:44      here: fedora-bootc:43
#
# — "silently, because nothing compared them". The lesson it drew was to keep
# one copy. These tests are the comparison for the copies that remain, so the
# next transition fails loudly here rather than shipping a variant built on a
# base nobody meant to ship.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
BUILD_CONFIG="${REPO_ROOT}/.github/build-config.yml"
REGISTRY_MAP="${REPO_ROOT}/registry-map.yaml"

setup() {
  command -v yq >/dev/null 2>&1 || skip "yq unavailable"
}

# The base_image build-config declares for a variant — the authoritative one.
# #1713 pinned refs with @sha256: digests; these tests compare tag-level pins
# (registry-map vs config), so strip the digest first.
config_base() {
  yq -r ".variants[] | select(.id == \"$1\") | .base_image" "$BUILD_CONFIG" \
    | sed 's/@sha256:.*//'
}

# The ref registry-map.yaml would resolve for a logical image name.
map_ref() {
  local host path tag
  host="$(yq -r ".registries.\"$(yq -r ".images.\"$1\".registry" "$REGISTRY_MAP")\"" "$REGISTRY_MAP")"
  path="$(yq -r ".images.\"$1\".path" "$REGISTRY_MAP")"
  tag="$(yq -r ".images.\"$1\".tag" "$REGISTRY_MAP")"
  echo "${host}/${path}:${tag}"
}

@test "registry-map's fedora-bootc pin matches bonito's build-config base" {
  # These agree today. The point is that nothing made them: registry-map is a
  # second copy of the Fedora base version, and a transition that bumps
  # build-config alone leaves it stale.
  [ "$(map_ref fedora-bootc)" = "$(config_base bonito)" ]
}

@test "registry-map's centos-bootc pin matches skipjack's build-config base" {
  [ "$(map_ref centos-bootc)" = "$(config_base skipjack)" ]
}

@test "registry-map's almalinux-bootc pin matches albacore's build-config base" {
  # This one has a real consumer — _registry.sh exports it as the default
  # BASE_IMAGE — so drift here is not merely cosmetic.
  [ "$(map_ref almalinux-bootc)" = "$(config_base albacore)" ]
}
