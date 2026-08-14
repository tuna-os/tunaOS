#!/usr/bin/env bats
# Base-version pins that must move together (tunaOS#1171).
#
# FEDORA-BASE-POLICY.md commits the project to tracking one Fedora stable at a
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
JUSTFILE="${REPO_ROOT}/Justfile"
INNER_SH="${REPO_ROOT}/scripts/build-image-inner.sh"

setup() {
  command -v yq >/dev/null 2>&1 || skip "yq unavailable"
}

# The base_image build-config declares for a variant — the authoritative one.
config_base() {
  yq -r ".variants[] | select(.id == \"$1\") | .base_image" "$BUILD_CONFIG"
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

@test "the two COREOS_STABLE_VERSION defaults agree" {
  # Justfile:5 defaults it to one value and build-image-inner.sh:81 to another.
  # Nothing in .github/workflows sets it, so the Justfile's value is what every
  # real build uses and the script's is a fallback for direct invocation — one
  # that had drifted two Fedora releases behind. Latent, not live, which is
  # precisely why it survived: no build ever took the branch that would have
  # shown it.
  local just_default inner_default
  just_default="$(sed -n 's/.*coreos_stable_version := env("COREOS_STABLE_VERSION", "\([0-9]*\)").*/\1/p' "$JUSTFILE")"
  inner_default="$(sed -n 's/.*COREOS_STABLE="\${COREOS_STABLE_VERSION:-\([0-9]*\)}".*/\1/p' "$INNER_SH")"
  [ -n "$just_default" ]
  [ -n "$inner_default" ]
  [ "$just_default" = "$inner_default" ]
}

@test "bonito's base and its description agree about the Fedora version" {
  # build-config carries the version twice per variant — in base_image and in
  # the human description that feeds docs and the image label. A transition
  # that bumps one and not the other ships an image that misreports itself.
  local base desc base_ver
  base="$(config_base bonito)"
  desc="$(yq -r '.variants[] | select(.id == "bonito") | .description' "$BUILD_CONFIG")"
  base_ver="${base##*:}"
  [[ "$desc" == *"$base_ver"* ]]
}

@test "FEDORA-BASE-POLICY.md names the file a transition actually has to edit" {
  # A currency policy that does not say where the version lives cannot be
  # executed. build-config.yml is the authoritative pin; the policy must point
  # at it, not just at the release cadence.
  run grep -F 'build-config.yml' "${REPO_ROOT}/FEDORA-BASE-POLICY.md"
  [ "$status" -eq 0 ]
}
