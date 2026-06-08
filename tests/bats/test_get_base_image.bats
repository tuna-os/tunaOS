#!/usr/bin/env bats
# Unit tests for scripts/get-base-image.sh
#
# Tests variant → base image URI mapping. This script is sourced
# by build-image.sh and every build variant depends on it.
#
# Run: bats tests/bats/test_get_base_image.bats

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"

setup() {
  SCRIPT="${REPO_ROOT}/scripts/get-base-image.sh"
}

# ── Variant mapping tests ────────────────────────────────────────────────────

@test "yellowfin → almalinux-bootc:10-kitten" {
  run bash "$SCRIPT" yellowfin
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/almalinuxorg/almalinux-bootc:10-kitten" ]
}

@test "almalinux-kitten alias → almalinux-bootc:10-kitten" {
  run bash "$SCRIPT" almalinux-kitten
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/almalinuxorg/almalinux-bootc:10-kitten" ]
}

@test "albacore → almalinux-bootc:10" {
  run bash "$SCRIPT" albacore
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/almalinuxorg/almalinux-bootc:10" ]
}

@test "almalinux alias → almalinux-bootc:10" {
  run bash "$SCRIPT" almalinux
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/almalinuxorg/almalinux-bootc:10" ]
}

@test "skipjack → centos-bootc:stream10" {
  run bash "$SCRIPT" skipjack
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/centos-bootc/centos-bootc:stream10" ]
}

@test "centos alias → centos-bootc:stream10" {
  run bash "$SCRIPT" centos
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/centos-bootc/centos-bootc:stream10" ]
}

@test "lts alias → centos-bootc:stream10" {
  run bash "$SCRIPT" lts
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/centos-bootc/centos-bootc:stream10" ]
}

@test "bonito → fedora-bootc:43" {
  run bash "$SCRIPT" bonito
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/fedora/fedora-bootc:43" ]
}

@test "fedora alias → fedora-bootc:43" {
  run bash "$SCRIPT" fedora
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/fedora/fedora-bootc:43" ]
}

@test "bluefin alias → fedora-bootc:43" {
  run bash "$SCRIPT" bluefin
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/fedora/fedora-bootc:43" ]
}

@test "bonito-rawhide → fedora-bootc:rawhide" {
  run bash "$SCRIPT" bonito-rawhide
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/fedora/fedora-bootc:rawhide" ]
}

@test "rawhide alias → fedora-bootc:rawhide" {
  run bash "$SCRIPT" rawhide
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/fedora/fedora-bootc:rawhide" ]
}

@test "redfin → rhel-bootc:latest" {
  run bash "$SCRIPT" redfin
  [ "$status" -eq 0 ]
  [ "$output" = "registry.redhat.io/rhel10/rhel-bootc:latest" ]
}

@test "rhel alias → rhel-bootc:latest" {
  run bash "$SCRIPT" rhel
  [ "$status" -eq 0 ]
  [ "$output" = "registry.redhat.io/rhel10/rhel-bootc:latest" ]
}

# ── Error handling ────────────────────────────────────────────────────────────

@test "unknown variant exits 1" {
  run bash "$SCRIPT" nonexistent_variant
  [ "$status" -eq 1 ]
}

@test "unknown variant writes to stderr" {
  run bash "$SCRIPT" not_a_real_variant
  [[ "$output" == *"Unknown variant"* ]]
}

@test "no argument exits 1" {
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
}

# ── Output format ─────────────────────────────────────────────────────────────

@test "output is a single line (no trailing whitespace)" {
  run bash "$SCRIPT" yellowfin
  [ "$status" -eq 0 ]
  # Output should be exactly one line
  [ "$(echo "$output" | wc -l)" -eq 1 ]
}

@test "all references start with registry prefix" {
  for variant in yellowfin albacore skipjack bonito redfin; do
    run bash "$SCRIPT" "$variant"
    [ "$status" -eq 0 ]
    [[ "$output" =~ ^(quay\.io|registry\.redhat\.io) ]]
  done
}
