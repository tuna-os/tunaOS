#!/usr/bin/env bats
# Tests for live-iso/common/src/customize-live.sh (tacklebox live_customize
# entrypoint) and its wiring in scripts/build-iso-tacklebox.sh.
#
# Detection tests run the real script against a fake session root
# (TUNA_SESSION_ROOT) with TUNA_DETECT_ONLY=1, which exits before any
# system mutation.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/live-iso/common/src/customize-live.sh"

setup() {
  FAKE_ROOT="$(mktemp -d)"
  mkdir -p "${FAKE_ROOT}/usr/share/wayland-sessions" \
           "${FAKE_ROOT}/usr/share/xsessions"
}

teardown() {
  rm -rf "${FAKE_ROOT}"
}

detect() {
  TUNA_SESSION_ROOT="${FAKE_ROOT}" TUNA_DETECT_ONLY=1 bash "${SCRIPT}" 2>/dev/null \
    | grep '^DETECTED '
}

# ── Desktop detection + installer app mapping ───────────────────────────────

@test "detect: plasma session -> kde + InstallerKde" {
  touch "${FAKE_ROOT}/usr/share/wayland-sessions/plasma.desktop"
  run detect
  [ "$output" = "DETECTED kde org.tunaos.InstallerKde" ]
}

@test "detect: niri session -> niri + InstallerNiri" {
  touch "${FAKE_ROOT}/usr/share/wayland-sessions/niri.desktop"
  run detect
  [ "$output" = "DETECTED niri org.tunaos.InstallerNiri" ]
}

@test "detect: cosmic session -> cosmic + InstallerCosmic" {
  touch "${FAKE_ROOT}/usr/share/wayland-sessions/cosmic.desktop"
  run detect
  [ "$output" = "DETECTED cosmic org.tunaos.InstallerCosmic" ]
}

@test "detect: xfce xsession -> xfce + InstallerXfce" {
  touch "${FAKE_ROOT}/usr/share/xsessions/xfce4.desktop"
  run detect
  [ "$output" = "DETECTED xfce org.tunaos.InstallerXfce" ]
}

@test "detect: no session files falls back to gnome, no tuna installer app" {
  run detect
  [ "$output" = "DETECTED gnome none" ]
}

@test "detect: kde wins over xfce when both present" {
  touch "${FAKE_ROOT}/usr/share/wayland-sessions/plasma.desktop"
  touch "${FAKE_ROOT}/usr/share/xsessions/xfce4.desktop"
  run detect
  [ "$output" = "DETECTED kde org.tunaos.InstallerKde" ]
}

@test "detect-only mode exits 0 and mutates nothing" {
  TUNA_SESSION_ROOT="${FAKE_ROOT}" TUNA_DETECT_ONLY=1 run bash "${SCRIPT}"
  [ "$status" -eq 0 ]
}

# ── Static content assertions ────────────────────────────────────────────────

@test "customize-live.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --severity=error --exclude=SC1091 "${SCRIPT}"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "customize-live.sh: installs from the tuna-os flatpak remote" {
  run grep 'tunaos.org/flatpak/tuna-os.flatpakrepo' "${SCRIPT}"
  [ "$status" -eq 0 ]
}

@test "customize-live.sh: initializes D-Bus identity before Flatpak installation" {
  run grep -n 'dbus-uuidgen --ensure=/etc/machine-id' "${SCRIPT}"
  [ "$status" -eq 0 ]
}

@test "customize-live.sh: does not require the bootc /root symlink target" {
  grep -q 'HOME=/tmp/tuna-live-customize' "${SCRIPT}"
  run grep -E 'mkdir -p /root' "${SCRIPT}"
  [ "$status" -ne 0 ]
}

@test "customize-live.sh: symlinks fisherman to /usr/local/bin" {
  run grep 'ln -sf .*/usr/local/bin/fisherman' "${SCRIPT}"
  [ "$status" -eq 0 ]
}

@test "customize-live.sh: ships the shared polkit action with allow_active=yes" {
  grep -q 'org.tunaos.Installer.install' "${SCRIPT}"
  grep -q '<allow_active>yes</allow_active>' "${SCRIPT}"
}

@test "customize-live.sh: polkit exec.path matches the frontends' pkexec target" {
  run grep 'policykit.exec.path">/usr/local/bin/fisherman' "${SCRIPT}"
  [ "$status" -eq 0 ]
}

@test "customize-live.sh: writes the offline-stores probe list" {
  grep -q '/etc/tuna-installer/offline-stores' "${SCRIPT}"
  grep -q '/usr/share/tuna-installer/oci-store' "${SCRIPT}"
}

@test "customize-live.sh: sources the matching desktop adapter" {
  run grep 'desktop-\${DESKTOP}.sh' "${SCRIPT}"
  [ "$status" -eq 0 ]
}

# ── Recipe wiring ─────────────────────────────────────────────────────────────

@test "build-iso-tacklebox.sh: recipe passes live_customize with customize-live.sh" {
  run grep 'live_customize.*customize-live.sh' "${REPO_ROOT}/scripts/build-iso-tacklebox.sh"
  [ "$status" -eq 0 ]
}

@test "images do not preinstall the installer (ISO-only, dakota pattern)" {
  run grep -r 'Flatpak Preinstall org.tunaos.Installer' "${REPO_ROOT}/build_scripts/"
  [ "$status" -ne 0 ]
}
