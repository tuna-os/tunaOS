#!/usr/bin/env bats
# test_cachyos_overlay.bats — tests for cachyos.sh overlay invariants.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CACHYOS_SH="${REPO_ROOT}/build_scripts/overlay/cachyos.sh"
CONTAINERFILE_ARCH="${REPO_ROOT}/Containerfile.arch"

@test "cachyos.sh removes stock kernel packages before installing linux-cachyos" {
  run grep -F 'pacman -Rdd --noconfirm linux linux-headers' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "cachyos.sh generates initramfs for every kernel in /usr/lib/modules without find | tail -1" {
  run grep -F "find /usr/lib/modules" "$CACHYOS_SH"
  [ "$status" -ne 0 ]
  run grep -F "for kdir in /usr/lib/modules/*/; do" "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "Containerfile.arch generates initramfs for every kernel in /usr/lib/modules without find | tail -1" {
  run grep -F "find /usr/lib/modules" "$CONTAINERFILE_ARCH"
  [ "$status" -ne 0 ]
  run grep -F "for kdir in /usr/lib/modules/*/; do" "$CONTAINERFILE_ARCH"
  [ "$status" -eq 0 ]
}
