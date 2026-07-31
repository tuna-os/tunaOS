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

@test "detect: no session files falls back to gnome, upstream bootc-installer app" {
  run detect
  [ "$output" = "DETECTED gnome org.bootcinstaller.Installer" ]
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

@test "customize-live.sh: gives headless Flatpak an explicit session bus" {
  grep -q 'DBUS_SESSION_BUS_ADDRESS' "${SCRIPT}"
  grep -q 'dbus-daemon --session' "${SCRIPT}"
}

@test "customize-live.sh: initializes D-Bus identity before Flatpak installation" {
  run grep -n 'systemd-machine-id-setup' "${SCRIPT}"
  [ "$status" -eq 0 ]
  grep -q 'rm -f /etc/machine-id' "${SCRIPT}"
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

@test "customize-live.sh: writes complete primary storage config for the overlay offline store" {
  grep -q 'cat >/etc/containers/storage.conf' "${SCRIPT}"
  grep -q 'driver = "overlay"' "${SCRIPT}"
  grep -q 'graphroot = "/var/lib/containers/storage"' "${SCRIPT}"
  grep -q 'additionalimagestores = \["/var/lib/superiso-store"\]' "${SCRIPT}"
  grep -q 'mount_program = "/usr/bin/fuse-overlayfs"' "${SCRIPT}"
}

# The primary config above is necessary but no longer sufficient:
# containers/storage 1.60+ (Rawhide) applies storage{,.rootful}.conf.d drop-ins
# after it, and containers-common's vendor drop-in replaces
# additionalimagestores with just /usr/lib/containers/storage. A 99- admin
# drop-in is applied last (drop-ins run in filename order), so it must re-list
# the offline store while keeping the vendor path bootc uses for bound images.
@test "customize-live.sh: re-asserts the offline store in a late drop-in" {
  grep -q 'storage.conf.d/99-tunaos-offline-store.conf' "${SCRIPT}"
  grep -q 'additionalimagestores = \[\${STORE_LIST}\]' "${SCRIPT}"
  grep -q "STORE_LIST='\"/var/lib/superiso-store\"'" "${SCRIPT}"
}

# ...but the vendor path only gets listed where it exists. containers/storage
# stats every additionalimagestores entry and fails the entire config when one
# is missing, so hardcoding Fedora's /usr/lib/containers/storage took podman
# down on Arch ("can't stat imageStore dir"). The offline store itself stays
# unconditional: it is mounted during boot, so it is absent at customize time.
@test "customize-live.sh: gates the vendor image store on it existing" {
  grep -q 'if \[\[ -d /usr/lib/containers/storage \]\]; then' "${SCRIPT}"
  # the heredoc delimiter must stay unquoted or STORE_LIST won't expand
  grep -q "cat >/etc/containers/storage.conf.d/99-tunaos-offline-store.conf <<CONFEOF" "${SCRIPT}"
}

# Only Containerfile.{el10,ubuntu} run build_scripts/40-services.sh, which is
# the sole place tunaos-live-ready.service gets enabled — the arch, opensuse,
# gentoo and debian bases shipped it disabled, so the e2e harness waited out
# its full ready timeout on a live session that was already up.
@test "customize-live.sh: enables the readiness marker in the live squash" {
  grep -q 'systemctl enable tunaos-live-ready.service' "${SCRIPT}"
  grep -q 'install -Dm644 "${SCRIPT_DIR}/tunaos-live-ready.service"' "${SCRIPT}"
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

@test "dev ISO marker enables SSH without changing production images" {
  grep -q '\.enable-sshd' "${REPO_ROOT}/scripts/build-iso-tacklebox.sh"
  grep -q 'tunaos-live-ssh-credentials.service' "${SCRIPT}"
  grep -q 'PasswordAuthentication yes' "${SCRIPT}"
  grep -q 'useradd --create-home' "${SCRIPT}"
  grep -q 'Requires=tunaos-live-ssh-credentials.service' "${SCRIPT}"
}

@test "images do not preinstall the installer (ISO-only, dakota pattern)" {
  run grep -r 'Flatpak Preinstall org.tunaos.Installer' "${REPO_ROOT}/build_scripts/"
  [ "$status" -ne 0 ]
}
