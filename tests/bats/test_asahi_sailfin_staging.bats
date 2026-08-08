#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
OVERLAY="${REPO_ROOT}/build_scripts/overlay/asahi.sh"
VERIFY="${REPO_ROOT}/scripts/verify-asahi-image.sh"

@test "Asahi overlay normalizes openSUSE Apple DTBs" {
  grep -q '/boot/dtb-${KVER}/apple' "$OVERLAY"
  grep -q '/usr/lib/modules/${KVER}/dtbs/apple' "$OVERLAY"
  grep -q '/usr/lib/modules/${KVER}/dtb/apple' "$OVERLAY"
}

@test "Asahi overlay normalizes openSUSE U-Boot payload" {
  grep -q '/boot/u-boot-nodtb.bin' "$OVERLAY"
  grep -q '/usr/lib/asahi-boot/u-boot-nodtb.bin' "$OVERLAY"
  grep -q '/boot/u-boot-nodtb.bin' "$VERIFY"
}
