#!/usr/bin/env bats
# BATS tests for build_scripts/ — container build stage scripts
#
# These scripts run inside container builds and are not designed for
# direct execution. Tests validate: existence, shebang, set flags,
# key function definitions, and shellcheck compliance.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# Test ALL build_scripts/*.sh files (not subdirectories)
build_scripts_top=(
  "00-workarounds" "10-base-packages" "20-packages"
  "26-packages-post" "40-services" "90-image-info"
  "DX" "HWE" "arch-customizations" "cleanup"
  "copy-files" "cosmic" "gnome" "kcm-ublue"
  "kde" "lib" "niri" "nvidia"
)

# ── Basic validation for all top-level build_scripts ──────────────────────

@test "build_scripts/lib.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/lib.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/lib.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/build_scripts/lib.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "build_scripts/lib.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/build_scripts/lib.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/lib.sh: defines pkg_install function" {
  run grep 'pkg_install()' "${REPO_ROOT}/build_scripts/lib.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/lib.sh: defines pkg_remove function" {
  run grep 'pkg_remove()' "${REPO_ROOT}/build_scripts/lib.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/lib.sh: computes CONTEXT_PATH" {
  run grep 'CONTEXT_PATH=' "${REPO_ROOT}/build_scripts/lib.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/lib.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/lib.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ── Stage scripts (sourced by the build system) ──────────────────────────

@test "build_scripts/00-workarounds.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/00-workarounds.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/00-workarounds.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/build_scripts/00-workarounds.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "build_scripts/00-workarounds.sh: has set flags" {
  run grep 'set -xeuo pipefail\|set -euo pipefail' "${REPO_ROOT}/build_scripts/00-workarounds.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/00-workarounds.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/00-workarounds.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "build_scripts/10-base-packages.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/10-base-packages.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/10-base-packages.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/build_scripts/10-base-packages.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "build_scripts/10-base-packages.sh: sources lib.sh" {
  run grep 'source.*lib.sh' "${REPO_ROOT}/build_scripts/10-base-packages.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/10-base-packages.sh: defines install_base_packages_no_de" {
  run grep 'install_base_packages_no_de()' "${REPO_ROOT}/build_scripts/10-base-packages.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/10-base-packages.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/10-base-packages.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "build_scripts/20-packages.sh: exists and sources lib.sh" {
  run grep 'source.*lib.sh' "${REPO_ROOT}/build_scripts/20-packages.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/20-packages.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/20-packages.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "build_scripts/40-services.sh: exists and sources lib.sh" {
  run grep 'source.*lib.sh' "${REPO_ROOT}/build_scripts/40-services.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/40-services.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/40-services.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "build_scripts/cleanup.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/cleanup.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/cleanup.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/copy-files.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/copy-files.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/copy-files.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/90-image-info.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/90-image-info.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/90-image-info.sh"
    [ "$status" -eq 0 ]
  fi
}

# ── Desktop flavor scripts ──────────────────────────────────────────────

@test "build_scripts/gnome.sh: exists and sources lib.sh" {
  run grep 'source.*lib.sh' "${REPO_ROOT}/build_scripts/gnome.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/gnome.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/gnome.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "build_scripts/kde.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/kde.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/kde.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/cosmic.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/cosmic.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/cosmic.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/niri.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/niri.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/niri.sh"
    [ "$status" -eq 0 ]
  fi
}

# ── Variant-specific scripts ────────────────────────────────────────────

@test "build_scripts/DX.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/DX.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/HWE.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/HWE.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/nvidia.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/nvidia.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/arch-customizations.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/arch-customizations.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/kcm-ublue.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/kcm-ublue.sh"
  [ "$status" -eq 0 ]
}

# ── bootc subdirectory scripts ──────────────────────────────────────────

@test "build_scripts/bootc/install-bootc.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/bootc/install-bootc.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/bootc/install-bootc.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/build_scripts/bootc/install-bootc.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "build_scripts/bootc/install-bootc.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/bootc/install-bootc.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "build_scripts/bootc/finalize.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/bootc/finalize.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/bootc/finalize.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/bootc/mount-system.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/bootc/mount-system.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/bootc/mount-system.sh"
    [ "$status" -eq 0 ]
  fi
}

# ── Override scripts ─────────────────────────────────────────────────────

@test "build_scripts/overrides/gdx/10-vscode.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/overrides/gdx/10-vscode.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/overrides/gdx/20-nvidia.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/overrides/gdx/20-nvidia.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/scripts/image-info-set: exists" {
  run test -f "${REPO_ROOT}/build_scripts/scripts/image-info-set"
  [ "$status" -eq 0 ]
}

# ── Config files (dracut, systemd, tmpfiles) ────────────────────────────

@test "build_scripts/bootc/sandbox dracut config: 20-bootc-base.conf exists" {
  run test -f "${REPO_ROOT}/build_scripts/bootc/sandbox/usr/lib/dracut/dracut.conf.d/20-bootc-base.conf"
  [ "$status" -eq 0 ]
}

@test "build_scripts/bootc/sandbox dracut config: 30-fix-bootc-modules.conf exists" {
  run test -f "${REPO_ROOT}/build_scripts/bootc/sandbox/usr/lib/dracut/dracut.conf.d/30-fix-bootc-modules.conf"
  [ "$status" -eq 0 ]
}

@test "build_scripts/bootc/sandbox systemd preset: 10-mount-system.preset exists" {
  run test -f "${REPO_ROOT}/build_scripts/bootc/sandbox/usr/lib/systemd/system-preset/10-mount-system.preset"
  [ "$status" -eq 0 ]
}

@test "build_scripts/bootc/sandbox tmpfiles: bootc-base-directories.conf exists" {
  run test -f "${REPO_ROOT}/build_scripts/bootc/sandbox/usr/lib/tmpfiles.d/bootc-base-directories.conf"
  [ "$status" -eq 0 ]
}
