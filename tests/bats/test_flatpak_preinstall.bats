#!/usr/bin/env bats
# Behavioral tests for build_scripts/desktop/flatpak-preinstall.sh.
#
# The script is sourced by install-desktop.sh in production; here it runs
# standalone against redirected paths (TUNAOS_PREINSTALL_DIR /
# TUNAOS_SYSTEMD_SYSTEM_DIR — same hook pattern as 40-services.sh) with
# systemctl stubbed on PATH, so the real logic is exercised, not grepped.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/desktop/flatpak-preinstall.sh"

setup() {
  PRE_DIR="${BATS_TEST_TMPDIR}/preinstall.d"
  UNIT_DIR="${BATS_TEST_TMPDIR}/systemd"
  mkdir -p "$UNIT_DIR" "${BATS_TEST_TMPDIR}/bin"
  cat > "${BATS_TEST_TMPDIR}/bin/systemctl" <<EOF
#!/usr/bin/env bash
echo "systemctl \$*" >> "${BATS_TEST_TMPDIR}/systemctl.log"
exit 0
EOF
  chmod +x "${BATS_TEST_TMPDIR}/bin/systemctl"
  # A flatpak that has the `preinstall` command, as on Fedora/EL.
  cat > "${BATS_TEST_TMPDIR}/bin/flatpak" <<'EOF'
#!/usr/bin/env bash
[[ "$1" == preinstall ]]
EOF
  chmod +x "${BATS_TEST_TMPDIR}/bin/flatpak"
}

run_script() {
  PATH="${BATS_TEST_TMPDIR}/bin:$PATH" \
    TUNAOS_PREINSTALL_DIR="$PRE_DIR" \
    TUNAOS_SYSTEMD_SYSTEM_DIR="$UNIT_DIR" \
    DESKTOP_FLAVOR="gnome" \
    run bash "$SCRIPT"
}

@test "declares the store and the browser for the desktop" {
  touch "${UNIT_DIR}/flatpak-preinstall.service"
  run_script
  [ "$status" -eq 0 ]
  grep -q '^\[Flatpak Preinstall io.github.kolunmi.Bazaar\]' "${PRE_DIR}/tunaos-gnome.preinstall"
  grep -q '^\[Flatpak Preinstall org.mozilla.firefox\]' "${PRE_DIR}/tunaos-gnome.preinstall"
  grep -q '^\[Flatpak Preinstall com.mattjakeman.ExtensionManager\]' "${PRE_DIR}/tunaos-gnome.preinstall"
}

@test "offers Extension Manager only on GNOME" {
  touch "${UNIT_DIR}/flatpak-preinstall.service"
  PATH="${BATS_TEST_TMPDIR}/bin:$PATH" \
    TUNAOS_PREINSTALL_DIR="$PRE_DIR" \
    TUNAOS_SYSTEMD_SYSTEM_DIR="$UNIT_DIR" \
    DESKTOP_FLAVOR="kde" \
    run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -rq 'com.mattjakeman.ExtensionManager' "$PRE_DIR"
}

@test "is idempotent — a second run adds no duplicate declarations" {
  touch "${UNIT_DIR}/flatpak-preinstall.service"
  run_script
  [ "$status" -eq 0 ]
  run_script
  [ "$status" -eq 0 ]
  [ "$(grep -c 'Flatpak Preinstall io.github.kolunmi.Bazaar' "${PRE_DIR}/tunaos-gnome.preinstall")" -eq 1 ]
}

@test "respects a pre-existing Bazaar declaration from the base image" {
  mkdir -p "$PRE_DIR"
  printf '[Flatpak Preinstall io.github.kolunmi.Bazaar]\nBranch=stable\nIsRuntime=false\n' \
    > "${PRE_DIR}/bazaar.preinstall"
  touch "${UNIT_DIR}/flatpak-preinstall.service"
  run_script
  [ "$status" -eq 0 ]
  # Bazaar stays declared once, in the pre-existing file; firefox is added.
  [ "$(grep -rc 'Flatpak Preinstall io.github.kolunmi.Bazaar' "$PRE_DIR" | awk -F: '{s+=$2} END {print s}')" -eq 1 ]
  grep -q 'Flatpak Preinstall org.mozilla.firefox' "${PRE_DIR}/tunaos-gnome.preinstall"
}

@test "enables flatpak-preinstall.service when the unit is shipped" {
  touch "${UNIT_DIR}/flatpak-preinstall.service"
  run_script
  [ "$status" -eq 0 ]
  grep -q 'systemctl enable flatpak-preinstall.service' "${BATS_TEST_TMPDIR}/systemctl.log"
}

@test "masks a shipped unit the base's flatpak cannot run" {
  # noble: projectbluefin/common ships the unit, flatpak 1.14 lacks the command.
  touch "${UNIT_DIR}/flatpak-preinstall.service"
  cat > "${BATS_TEST_TMPDIR}/bin/flatpak" <<'EOF'
#!/usr/bin/env bash
echo "error: '$1' is not a flatpak command. Did you mean 'install'?" >&2
exit 1
EOF
  run_script
  [ "$status" -eq 0 ]
  grep -qx 'systemctl mask flatpak-preinstall.service' "${BATS_TEST_TMPDIR}/systemctl.log"
  ! grep -q 'systemctl enable' "${BATS_TEST_TMPDIR}/systemctl.log"
  [[ "$output" == *"has no 'preinstall'"* ]]
}

@test "warns instead of failing when the base ships no preinstall unit" {
  run_script
  [ "$status" -eq 0 ]
  [[ "$output" == *"flatpak-preinstall.service is not shipped"* ]]
  [ ! -f "${BATS_TEST_TMPDIR}/systemctl.log" ]
}

@test "a failing enable fails the build instead of being swallowed" {
  touch "${UNIT_DIR}/flatpak-preinstall.service"
  cat > "${BATS_TEST_TMPDIR}/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
  chmod +x "${BATS_TEST_TMPDIR}/bin/systemctl"
  run_script
  [ "$status" -ne 0 ]
}
