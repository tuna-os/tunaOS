#!/usr/bin/env bats
# BATS tests for build_scripts/ — container build stage scripts
#
# These scripts run inside container builds and are not designed for
# direct execution. Tests validate: existence, shebang, set flags,
# key function definitions, and shellcheck compliance.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

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

# tunaOS#951. openssh-server was installed in exactly ONE place — the apt
# branch, under ENABLE_SSHD=1 — and nowhere at all for pacman or zypper. The
# rpm variants only worked because their base images ship it. customize-live.sh
# then aborted every dev ISO with "no SSH service is installed", which gates
# every LUKS and installer cell: flounder, flounder-sid, grouper, marlin and
# sailfin were structurally untestable, not merely under-tested.
@test "build_scripts/40-services.sh: every package manager can install openssh" {
  local f="${REPO_ROOT}/build_scripts/40-services.sh"
  # Arch calls it `openssh`, Gentoo needs the atom, the rest use openssh-server.
  # Anchored past the package name so `openssh` cannot be satisfied by a line
  # that actually says `openssh-server` — on Arch that package does not exist.
  grep -qE 'pacman\)[[:space:]]*pkg_install openssh[[:space:]]*;;' "$f"
  grep -qE 'emerge\)[[:space:]]*pkg_install net-misc/openssh' "$f"
  grep -qE 'zypper\)[[:space:]]*pkg_install openssh-server' "$f"
  grep -qE '\*\)[[:space:]]*pkg_install openssh-server' "$f"
}

# Both branches must call it: the apt branch exits early, so a single call
# sited in either one silently skips the other family. That asymmetry is the
# original bug, not an incidental detail of it.
@test "build_scripts/40-services.sh: both the apt and non-apt paths ensure openssh" {
  local f="${REPO_ROOT}/build_scripts/40-services.sh"
  run bash -c "grep -c '^[[:space:]]*ensure_openssh_installed$' '$f'"
  [ "$status" -eq 0 ]
  [ "$output" -ge 2 ]
  # ...and neither call may be nested under an ENABLE_SSHD test. A call
  # indented two tabs or more is inside that branch, which is the bug.
  ! grep -qE '^\t\t+ensure_openssh_installed$' "$f"
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
    # -F: the dots are literal, so ssh.service must not match e.g. sshXservice.
    echo "$output" | grep -qF "safe_disable ${unit}"
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

# The archlinux/archlinux container overwrites /etc/os-release with a regular
# file holding stock Arch identity, shadowing the `filesystem` package symlink
# to /usr/lib/os-release. Branding only the canonical file left marlin shipping
# two identities, and verify-branding.sh (which prefers /etc/os-release) failed
# all ten identity/logo checks against a correctly branded /usr/lib/os-release.
@test "build_scripts/90-image-info.sh brands every distinct os-release path" {
  local script="${REPO_ROOT}/build_scripts/90-image-info.sh"
  # The two paths default to the real ones and are overridable for the
  # behavioural fixtures in test_build_scripts_remaining.bats only.
  grep -q 'OS_RELEASE_USR="\${TUNAOS_OS_RELEASE_USR:-/usr/lib/os-release}"' "$script"
  grep -q 'OS_RELEASE_ETC="\${TUNAOS_OS_RELEASE_ETC:-/etc/os-release}"' "$script"
  grep -q 'OS_RELEASE_FILES=("\$OS_RELEASE_USR")' "$script"
  grep -q 'OS_RELEASE_FILES+=("\$OS_RELEASE_ETC")' "$script"
  # Every write goes through osr_set, which iterates the list.
  run grep -cE '\$\{OS_RELEASE_FILES\[@\]\}' "$script"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
  # No write may target /usr/lib/os-release directly any more.
  run grep -nE '(sed -i[^|]*|>>)[[:space:]]*/usr/lib/os-release' "$script"
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

# desktop/cosmic.sh is gone: every Containerfile now installs COSMIC through
# the manifest installer, so the script had no callers left. See
# tests/bats/test_desktop_script_apt_branch.bats for the check that keeps the
# remaining per-DE scripts honest about the bases that call them.

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
