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

@test "build_scripts/01-workarounds.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/01-workarounds.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/01-workarounds.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/build_scripts/01-workarounds.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "build_scripts/01-workarounds.sh: has set flags" {
  run grep 'set -xeuo pipefail\|set -euo pipefail' "${REPO_ROOT}/build_scripts/01-workarounds.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/01-workarounds.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/01-workarounds.sh"
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

@test "build_scripts/10-base-packages.sh: is a direct executable (no function wrapper)" {
  # The script should NOT define a function — it runs directly like all other numbered scripts
  run grep 'install_base_packages_no_de()' "${REPO_ROOT}/build_scripts/10-base-packages.sh"
  [ "$status" -ne 0 ]
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

# tunaOS#951. openssh-server used to be apt-installed only under
# ENABLE_SSHD=1, so on Debian/Ubuntu the package was absent rather than the
# service merely disabled — and customize-live.sh then aborted every dev ISO
# with "no SSH service is installed", taking every flounder/flounder-sid LUKS
# and installer cell with it. The install must not sit inside that branch.
@test "build_scripts/40-services.sh: apt installs openssh-server unconditionally" {
  run awk '/^if \[\[ "\$\{PKG_MGR:-\}" == "apt" \]\]/,/^fi$/' \
    "${REPO_ROOT}/build_scripts/40-services.sh"
  [ "$status" -eq 0 ]
  # The install line exists in the apt block...
  echo "$output" | grep -q 'apt-get install .*openssh-server'
  # ...and is NOT indented under the ENABLE_SSHD test (two tabs or deeper).
  ! echo "$output" | grep -qE '^\t\t+apt-get install .*openssh-server'
}

# The unconditional install above is only safe if the disabled path actually
# disables it: Debian's openssh-server postinst ENABLES ssh.service, and the
# real unit is ssh.service (sshd.service is a compat symlink). Missing the
# Debian spelling would ship published images with sshd running.
@test "build_scripts/40-services.sh: apt disables both Debian SSH unit names" {
  run awk '/^if \[\[ "\$\{PKG_MGR:-\}" == "apt" \]\]/,/^fi$/' \
    "${REPO_ROOT}/build_scripts/40-services.sh"
  [ "$status" -eq 0 ]
  for unit in sshd.service ssh.service sshd.socket ssh.socket; do
    echo "$output" | grep -q "safe_disable ${unit}"
  done
}

@test "build_scripts/99-cleanup.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/99-cleanup.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/99-cleanup.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/00-copy-files.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/00-copy-files.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/00-copy-files.sh"
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

@test "build_scripts/90-image-info.sh maps variants to scientific fish names" {
  local script="${REPO_ROOT}/build_scripts/90-image-info.sh"
  grep -q 'yellowfin) CODE_NAME="Thunnus albacares"' "$script"
  grep -q 'albacore) CODE_NAME="Thunnus alalunga"' "$script"
  grep -q 'skipjack) CODE_NAME="Katsuwonus pelamis"' "$script"
  grep -q 'grouper) CODE_NAME="Epinephelus marginatus"' "$script"
  run grep -F 'CODE_NAME="Achillobator"' "$script"
  [ "$status" -ne 0 ]
}

# ── Desktop flavor scripts ──────────────────────────────────────────────

@test "build_scripts/desktop/gnome.sh: exists and sources lib.sh" {
  run grep 'source.*lib.sh' "${REPO_ROOT}/build_scripts/desktop/gnome.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/desktop/gnome.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/desktop/gnome.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "build_scripts/desktop/kde.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/desktop/kde.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/desktop/kde.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/desktop/cosmic.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/desktop/cosmic.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/desktop/cosmic.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/desktop/niri.sh: exists and passes shellcheck" {
  run test -f "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  [ "$status" -eq 0 ]
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/desktop/niri.sh"
    [ "$status" -eq 0 ]
  fi
}

@test "build_scripts/desktop/niri.sh: Ubuntu uses the AvengeMedia Niri and DMS repositories" {
  grep -q 'avengemedia/danklinux/ubuntu' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'avengemedia/dms/ubuntu' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'codename="${UBUNTU_CODENAME:-${VERSION_CODENAME' \
    "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'pkg_install niri greetd quickshell dms dms-greeter' \
    "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'libpam-gnome-keyring' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'python3-nautilus' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'ssh-askpass-gnome' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'systemd-zram-generator' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'twpayne/chezmoi/releases/download' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'sha256sum -c' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  grep -q 'chezmoi --version' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  run grep -E 'pkg_install .*greetd-spawn' "${REPO_ROOT}/build_scripts/desktop/niri.sh"
  [ "$status" -ne 0 ]
}

# ── Variant-specific scripts ────────────────────────────────────────────

@test "build_scripts/overlay/hwe.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/overlay/hwe.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/overlay/nvidia.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/overlay/nvidia.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/91-arch-customizations.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/91-arch-customizations.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/desktop/kcm-ublue.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/desktop/kcm-ublue.sh"
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
