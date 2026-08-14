#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CACHYOS_SH="${REPO_ROOT}/build_scripts/overlay/cachyos.sh"

@test "CachyOS overlay does not upgrade the stock kernel during install" {
  run grep -E '^pacman -Syu' "$CACHYOS_SH"
  [ "$status" -ne 0 ]
  run grep -E '^pacman -S --noconfirm --needed' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "CachyOS overlay removes the stock linux kernel when installed" {
  run grep -F 'pacman -Qq linux' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  run grep -F 'pacman -Rdd --noconfirm linux' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "CachyOS overlay builds initramfs for the only module tree" {
  run grep -F 'expected exactly one kernel module tree' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  run grep -F 'dracut --force --omit "tpm2-tss" "${_kernel_dir}/initramfs.img" "${_kernel}"' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  run grep -F 'tail -1' "$CACHYOS_SH"
  [ "$status" -ne 0 ]
}
