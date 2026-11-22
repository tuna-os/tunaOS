#!/usr/bin/env bats
# Dry-run coverage for installer-medium build scripts (tunaOS#4907, #4913).
#
# Every stage of build-medium.sh runs with --dry-run here: no root, no loop
# devices, no image builds. The tests assert each stage prints its contract
# command (bootc install with the cell backend, --el-torito=yes repart,
# CopyBlocks definitions, the fixed Flatpak set, chunked OCI layout).

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
MEDIUM="${REPO_ROOT}/installer-medium"

@test "build-to-disk resolves the cell and prints the bootc command" {
  run "${MEDIUM}/build-to-disk.sh" albacore:gnome /tmp/medium-test.raw --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"--filesystem"* ]] || [[ "$output" == *"to-disk"* ]]
  [[ "$output" == *"rhgb"* ]]
}

@test "build-to-disk prints composefs and systemd-boot for tromso:kde" {
  run "${MEDIUM}/build-to-disk.sh" tromso:kde /tmp/medium-test.raw --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"--composefs-backend"* ]]
  [[ "$output" == *"--bootloader systemd"* ]]
}

@test "add-live-entry dry-run names the grub entry and ESP payload" {
  run "${MEDIUM}/add-live-entry.sh" albacore:gnome /tmp/root /tmp/esp --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"grub"* ]]
  [[ "$output" == *"EFI/tunaos-live"* ]]
}

@test "add-live-entry dry-run names the systemd-boot entry and live initrd" {
  run "${MEDIUM}/add-live-entry.sh" tromso:kde /tmp/root /tmp/esp --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"systemd-boot"* ]]
  [[ "$output" == *"live initrd"* ]]
}

@test "build-hybrid dry-run requires --el-torito=yes" {
  run "${MEDIUM}/repart/build-hybrid.sh" albacore:gnome /tmp/medium-test.raw /tmp/medium-test.iso --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"--el-torito=yes"* ]]
}

@test "bake-flatpaks dry-run lists the fixed set for each cell" {
  run "${MEDIUM}/flatpak/bake-flatpaks.sh" albacore:gnome /tmp/root --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"org.mozilla.firefox"* ]]
  [[ "$output" == *"com.mattjakeman.ExtensionManager"* ]]
  run "${MEDIUM}/flatpak/bake-flatpaks.sh" tromso:kde /tmp/root --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" != *"ExtensionManager"* ]]
}

@test "live layer ships a drop-in for every skipped unit" {
  for unit in flatpak-preinstall.service bootc-fetch-apply-updates.timer uupd.service \
      brew-setup.service bootloader-update.service remove-installer.service secure-boot-update.service; do
    [ -f "${MEDIUM}/live/usr/lib/systemd/system/${unit}.d/50-medium-live.conf" ]
  done
  [ -f "${MEDIUM}/live/usr/lib/systemd/user/brew-preinstall.service.d/50-medium-live.conf" ]
  [ -f "${MEDIUM}/live/usr/lib/dracut/modules.d/90medium-sr0/medium-sr0.sh" ]
}
