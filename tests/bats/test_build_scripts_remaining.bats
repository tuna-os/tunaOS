#!/usr/bin/env bats
# BATS tests for remaining untested build scripts and live-iso scripts

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# ═══════════════════════════════════════════════════════════════════════════
# build_scripts/26-packages-post.sh
# ═══════════════════════════════════════════════════════════════════════════

@test "build_scripts/26-packages-post.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/26-packages-post.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [[ "$output" =~ ^#!/.*bash ]]
}

@test "build_scripts/26-packages-post.sh: has set flags" {
  run grep 'set -xeuo pipefail' "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/26-packages-post.sh: defines SCRIPTS_PATH" {
  run grep 'SCRIPTS_PATH=' "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/26-packages-post.sh: creates DOWNLOADS_DIR" {
  run grep 'DOWNLOADS_DIR' "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/26-packages-post.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck "${REPO_ROOT}/build_scripts/26-packages-post.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# live-iso/common/src/desktop-gnome.sh
# ═══════════════════════════════════════════════════════════════════════════

@test "live-iso/common/src/desktop-gnome.sh: exists" {
  run test -f "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-gnome.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [[ "$output" =~ ^#!/.*bash ]]
}

@test "live-iso/common/src/desktop-gnome.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-gnome.sh: configures GNOME dock" {
  run grep 'favorite-apps' "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-gnome.sh: disables suspend" {
  run grep 'suspend\|sleep' "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-gnome.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# live-iso/common/src/desktop-kde.sh
# ═══════════════════════════════════════════════════════════════════════════

@test "live-iso/common/src/desktop-kde.sh: exists" {
  run test -f "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-kde.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [[ "$output" =~ ^#!/.*bash ]]
}

@test "live-iso/common/src/desktop-kde.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-kde.sh: configures SDDM autologin" {
  run grep 'sddm\|autologin' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-kde.sh: disables screen lock" {
  run grep 'lock\|suspend' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-kde.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}
