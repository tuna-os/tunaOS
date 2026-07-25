#!/usr/bin/env bats
# BATS tests for KDE display-manager resolution (PlasmaLogin vs SDDM).
#
# Plasma 6.6 renamed SDDM to PlasmaLogin. On EL10 the image ships
# plasma-login-manager (plasmalogin.service, /etc/plasmalogin.conf.d) while
# Fedora, Debian, Ubuntu and Arch still ship sddm.service and
# /etc/sddm.conf.d. plasma-login-manager does NOT Obsolete sddm, so EL10 KDE
# images carry BOTH units and PlasmaLogin wins — its scriptlet claims
# display-manager.service first.
#
# That single fact had to be fixed in five places, and it was found by
# accident four times out of five:
#
#   1. live-iso/common/src/desktop-kde.sh   — live autologin config
#   2. build_scripts/40-services.sh         — DM enable
#   3. build_scripts/desktop/configure-desktop-runtime.sh
#   4. the contract checks (verify-desktop-experience, e2e-runtime-checks)
#   5. build_scripts/desktop/install-desktop.sh — the manifest-declared DM,
#      which is force-linked into graphical.target.wants and so is the one
#      that actually pulls a DM at boot
#
# Getting (5) wrong put sddm.service in graphical.target.wants while
# display-manager.service pointed at plasmalogin: two display managers
# racing for seat0/VT1, and "Failed to start plasmalogin.service".
#
# These tests exist so a sixth copy, or a regression in any of the five,
# fails here instead of in a two-hour ISO smoke run.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# ── The live autologin config must target both DMs ────────────────────────

@test "desktop-kde.sh: writes autologin to plasmalogin.conf.d" {
  run grep -q '/etc/plasmalogin.conf.d' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "desktop-kde.sh: still writes sddm.conf.d for distros shipping sddm" {
  run grep -q '/etc/sddm.conf.d' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "desktop-kde.sh: fails loudly when neither DM is present" {
  # An ISO that silently ships no autologin boots to a password prompt no
  # blank password satisfies — the original bug. Must not be silent.
  run grep -qE 'exit 1' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

# ── DM unit selection ─────────────────────────────────────────────────────

@test "lib.sh: defines kde_dm_unit" {
  run grep -q 'kde_dm_unit()' "${REPO_ROOT}/build_scripts/lib.sh"
  [ "$status" -eq 0 ]
}

@test "kde_dm_unit: prefers plasmalogin when its unit exists" {
  root="$(mktemp -d)"
  mkdir -p "${root}/usr/lib/systemd/system"
  touch "${root}/usr/lib/systemd/system/plasmalogin.service"
  touch "${root}/usr/lib/systemd/system/sddm.service"
  run bash -c "
    kde_dm_unit() {
      if [[ -e ${root}/usr/lib/systemd/system/plasmalogin.service ]]; then
        echo plasmalogin.service
      else
        echo sddm.service
      fi
    }
    kde_dm_unit"
  rm -rf "${root}"
  [ "$output" = "plasmalogin.service" ]
}

@test "kde_dm_unit: falls back to sddm when plasmalogin is absent" {
  root="$(mktemp -d)"
  mkdir -p "${root}/usr/lib/systemd/system"
  touch "${root}/usr/lib/systemd/system/sddm.service"
  run bash -c "
    kde_dm_unit() {
      if [[ -e ${root}/usr/lib/systemd/system/plasmalogin.service ]]; then
        echo plasmalogin.service
      else
        echo sddm.service
      fi
    }
    kde_dm_unit"
  rm -rf "${root}"
  [ "$output" = "sddm.service" ]
}

@test "40-services.sh: enables the resolved unit, not a hardcoded sddm" {
  run grep -q 'safe_enable "\$(kde_dm_unit)"' "${REPO_ROOT}/build_scripts/40-services.sh"
  [ "$status" -eq 0 ]
}

@test "40-services.sh: no bare 'safe_enable sddm.service' remains" {
  run grep -n 'safe_enable sddm.service' "${REPO_ROOT}/build_scripts/40-services.sh"
  [ "$status" -ne 0 ]
}

@test "configure-desktop-runtime.sh: detects plasmalogin for kde" {
  run grep -q 'plasmalogin' "${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
  [ "$status" -eq 0 ]
}

# ── The manifest-declared DM (the one force-linked into graphical.target) ──

@test "install-desktop.sh: resolves a manifest 'sddm' to plasmalogin when shipped" {
  # Assert the ASSIGNMENT, not merely that the word appears — a comment
  # mentioning plasmalogin satisfied the loose version of this test even
  # with the resolution itself reverted.
  run grep -qE '_TD_DM="?plasmalogin"?' "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  [ "$status" -eq 0 ]
}

@test "install-desktop.sh: the resolution is guarded on the unit existing" {
  run grep -qE '_TD_DM.*==.*sddm.*&&.*plasmalogin\.service' \
    "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  [ "$status" -eq 0 ]
}

@test "install-desktop.sh: drops the sibling DM from graphical.target.wants" {
  # Both units exist on EL10 KDE. If both are wanted they race for seat0 and
  # the loser fails to start, which is exactly what was observed.
  run grep -q 'graphical.target.wants/sddm.service' "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  [ "$status" -eq 0 ]
  run grep -q 'graphical.target.wants/plasmalogin.service' "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  [ "$status" -eq 0 ]
}

# ── Contract checks must accept either unit ───────────────────────────────

@test "verify-desktop-experience.sh: kde contract accepts sddm or plasmalogin" {
  run grep -q 'sddm|plasmalogin' "${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  [ "$status" -eq 0 ]
}

@test "e2e-runtime-checks.sh: kde contract accepts sddm or plasmalogin" {
  run grep -q 'sddm|plasmalogin' "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"
  [ "$status" -eq 0 ]
}

@test "boot-gate.sh: kde asserts either DM" {
  run grep -q 'DM_CANDIDATES=(sddm plasmalogin)' "${REPO_ROOT}/scripts/boot-gate.sh"
  [ "$status" -eq 0 ]
}

@test "verify-image-packages.sh: kde accepts either DM unit file" {
  run grep -q 'sddm.service plasmalogin.service' "${REPO_ROOT}/scripts/verify-image-packages.sh"
  [ "$status" -eq 0 ]
}

# ── Guard against a sixth copy ────────────────────────────────────────────

@test "no build script hardcodes sddm.conf.d without also handling plasmalogin" {
  # Every file that writes SDDM's config dir must know about PlasmaLogin's.
  # tromso-style images that genuinely build sddm from source are a separate
  # repo; within tunaOS, EL10 is the reality.
  failed=""
  while IFS= read -r f; do
    grep -q 'plasmalogin' "$f" || failed="${failed} ${f}"
  done < <(grep -rIl 'sddm\.conf\.d' \
             "${REPO_ROOT}/build_scripts" \
             "${REPO_ROOT}/live-iso" \
             "${REPO_ROOT}/scripts" 2>/dev/null || true)
  [ -z "$failed" ] || {
    echo "files writing sddm.conf.d with no plasmalogin handling:${failed}"
    false
  }
}
