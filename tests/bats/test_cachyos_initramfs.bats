#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "CachyOS overlay removes the stock kernel" {
  run grep -F 'pacman -Rdd --noconfirm linux' \
    "${REPO_ROOT}/build_scripts/overlay/cachyos.sh"
  [ "$status" -eq 0 ]
}

@test "CachyOS overlay builds initramfs for every kernel tree" {
  run grep -F 'for kernel_dir in /usr/lib/modules/*' \
    "${REPO_ROOT}/build_scripts/overlay/cachyos.sh"
  [ "$status" -eq 0 ]
  run grep -F 'for kernel_dir in "${kernel_dirs[@]}"' \
    "${REPO_ROOT}/build_scripts/overlay/cachyos.sh"
  [ "$status" -eq 0 ]
}

@test "CachyOS and Arch image builds do not choose a kernel with find tail" {
  run grep -nE 'find .*\/usr/lib/modules.*tail -1' \
    "${REPO_ROOT}/build_scripts/overlay/cachyos.sh"
  [ "$status" -ne 0 ]
  run grep -nE 'find .*\/usr/lib/modules.*tail -1' \
    "${REPO_ROOT}/Containerfile.arch"
  [ "$status" -ne 0 ]
}
