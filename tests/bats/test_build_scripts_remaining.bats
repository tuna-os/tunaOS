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
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/26-packages-post.sh"
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
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
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
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "desktop experience contract covers upstream experience families" {
  local script="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  run grep -F 'projectbluefin/bluefin-lts' "$script"
  [ "$status" -eq 0 ]
  run grep -F 'ublue-os/aurora' "$script"
  [ "$status" -eq 0 ]
  run grep -F 'zirconium-dev/zirconium' "$script"
  [ "$status" -eq 0 ]
}

@test "desktop experience contract covers every shipped DE" {
  local script="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  for de in gnome kde niri cosmic xfce; do
    grep -qE "^${de}\)|\| ${de}\)|${de} \|" "$script"
  done
  # Runtime DM validation must use the distro-agnostic alias, not raw unit
  # names (gdm vs gdm3 vs lightdm drift across variants).
  grep -qF 'display-manager.service' "$script"
}

@test "disk gate requires the desktop contract marker" {
  # e9fe9e5: the gate deliberately accepts OK or FAIL — either proves the
  # contract service ran (graphical.target reached, DM started).
  run grep -F 'TUNAOS_DESKTOP_CONTRACT_(OK|FAIL)' "${REPO_ROOT}/scripts/iso-e2e.sh"
  [ "$status" -eq 0 ]
}

@test "desktop installer makes graphical target the boot default" {
  run grep -F 'systemctl set-default graphical.target' \
    "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  [ "$status" -eq 0 ]
}

@test "Ubuntu desktop stages configure display manager after package installation" {
  run grep -F 'configure-desktop-runtime.sh niri' "${REPO_ROOT}/Containerfile.ubuntu"
  [ "$status" -eq 0 ]
  grep -q 'systemctl enable "${dm}.service"' \
    "${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
  grep -q 'tunaos-desktop-contract.service' \
    "${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
}

@test "published image contract executes and records pinned Remora" {
  local post="${REPO_ROOT}/build_scripts/26-packages-post.sh"
  grep -q 'sha256sum --check --strict' "$post"
  grep -q "remora --help" "$post"
  grep -q 'experience-contracts/remora' "$post"
  # Runtime contract still gates on remora being present in the image.
  grep -q 'remora_not_found' \
    "${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
}

@test "desktop contract unit runs the installed-system TAP checks on all DEs" {
  # Both installer paths (manifest-driven and Ubuntu runtime-configure) must
  # bake e2e-runtime-checks and run it as a non-fatal second ExecStart.
  for script in install-desktop.sh configure-desktop-runtime.sh; do
    grep -q 'e2e-runtime-checks.sh' "${REPO_ROOT}/build_scripts/desktop/${script}"
    grep -qF 'ExecStart=-/usr/libexec/tunaos/e2e-runtime-checks' \
      "${REPO_ROOT}/build_scripts/desktop/${script}"
    # Contract gate covers every DE, not just gnome/kde/niri.
    grep -q 'cosmic' "${REPO_ROOT}/build_scripts/desktop/${script}"
    grep -q 'xfce' "${REPO_ROOT}/build_scripts/desktop/${script}"
  done
}

@test "build contract statically verifies units and launchers, hard-fails KDE skew" {
  local script="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  # secureblue pattern: validate the enabled unit graph (system + user).
  grep -qF 'systemd-analyze verify --recursive-errors=yes graphical.target' "$script"
  grep -qF 'systemd-analyze verify --user --recursive-errors=yes default.target' "$script"
  grep -q 'SYSTEMD_VERIFY_FATAL' "$script"
  # aurora pattern: desktop-file-validate shipped launchers (warn-only default).
  grep -q 'desktop-file-validate' "$script"
  grep -q 'DESKTOP_VALIDATE_FATAL' "$script"
  # aurora pattern: Plasma/Qt version-skew is a hard build failure.
  grep -q 'KDE version skew' "$script"
  grep -q 'Qt version skew' "$script"
  # runtime side re-verifies the unit graph on the installed system.
  grep -qF 'systemd-analyze verify --recursive-errors=yes graphical.target' \
    "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"
}

@test "EL10 KDE does not copy nonexistent Aurora files from Bluefin common" {
  run grep -F 'COPY --from=common /system_files/aurora' \
    "${REPO_ROOT}/Containerfile.el10"
  [ "$status" -ne 0 ]
}
