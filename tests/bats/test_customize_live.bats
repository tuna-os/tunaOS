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
  # Asserts the MECHANISM, not one spelling of it. This used to grep for the
  # literal `dbus-daemon --session`, which 886444e3 replaced with a `_start_bus`
  # helper (the forked bus was holding the build's stdout pipe open and turning
  # a 1-second failure into a 57-minute timeout). The session bus was still
  # started and still exported, but the string was gone, so this test failed on
  # a script that behaves correctly — and it failed on every PR in the repo, not
  # just the ones touching live-iso, because Unit Tests runs the whole bats
  # suite and the commit did not grep for tests pinning the old wording.
  grep -q 'DBUS_SESSION_BUS_ADDRESS' "${SCRIPT}"
  # a session bus is started (the space rules out the helper's own definition
  # line, and the class rules out a comment or a pipeline carrying the flag)...
  grep -qE '_start_bus [^#|]*--session' "${SCRIPT}"
  # ...and the thing that starts it really does exec dbus-daemon.
  grep -q 'dbus-daemon "$@"' "${SCRIPT}"
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
  grep -q 'additionalimagestores = ${STORE_LIST}' "${SCRIPT}"
  grep -q 'mount_program = "/usr/bin/fuse-overlayfs"' "${SCRIPT}"
}

# tunaOS#972: the vendor store is a Fedora/EL bootc convention. openSUSE ships
# no /usr/lib/containers/storage and the overlay driver hard-fails on a store
# it cannot stat, so the list must be composed from directories that exist.
@test "customize-live.sh: enumerates only image stores that exist" {
  grep -q 'VENDOR_STORE="/usr/lib/containers/storage"' "${SCRIPT}"
  grep -q 'IMAGE_STORES=("\$STORE_MOUNT")' "${SCRIPT}"
  grep -q 'if \[\[ -d "\$VENDOR_STORE" \]\]; then' "${SCRIPT}"
  grep -q 'IMAGE_STORES+=("\$VENDOR_STORE")' "${SCRIPT}"
}

# tunaOS#881: the primary config is necessary but not sufficient —
# /usr/share/containers/storage.conf.d/00-vendor.conf is applied after it and
# REPLACES additionalimagestores wholesale. The 99- drop-in must outrank it and
# must enumerate the same stores, since the last writer of an array wins.
@test "customize-live.sh: outranks the vendor drop-in and keeps both stores" {
  grep -q 'cat >/etc/containers/storage.conf.d/99-tbox-offline-store.conf' "${SCRIPT}"
  run grep -c 'additionalimagestores = ${STORE_LIST}' "${SCRIPT}"
  [ "$output" -eq 2 ]
}

# tunaOS#972: mounts.conf is the subscriptions mechanism, not a bind mount —
# containers/common copies the whole source directory into the container's
# runroot, which on live media is a tmpfs. Listing the payload store there
# duplicated a 3 GB image into RAM and took out sailfin:gnome twice (OOM in run
# 30730744132, ENOSPC on /run in run 30731534696). fisherman bind-mounts the
# store itself when a path needs it, so this file must not be written.
@test "customize-live.sh: never lists the offline store in mounts.conf" {
  # The comment explaining why may name the file; a write to it must not exist.
  run grep -n '^[^#]*>[[:space:]]*[^ ]*mounts\.conf' "${SCRIPT}"
  [ "$status" -ne 0 ]
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

@test "weekly desktop screenshots use host networking for tacklebox customize" {
  run grep 'sudo TBOX_CUSTOMIZE_NETWORK=host' \
    "${REPO_ROOT}/.github/workflows/weekly-desktop-screenshots.yml"
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

# ── Bounded network operations ──────────────────────────────────────────────
#
# tacklebox does not surface customize output, so a hung network fetch in this
# script is indistinguishable from progress: the build log shows
# "[customize] running 2 script(s)" and then nothing until the job cap. That
# is precisely how grouper:cosmic burned two runs — 3h52m in [customize]
# until the 240-minute cap killed the second (run 31144135208), where every
# other flavor clears the phase in ~2 minutes. flatpak has no network
# deadline of its own and curl's --retry does not bound a stalled transfer.
#
# These pin every network operation in the installer-flatpak block to a
# deadline, so a stall becomes the WARN-and-continue arm (dev/E2E media) or a
# visible failure (release media) rather than a silent 4-hour wedge.

@test "both installer flatpak installs run under timeout" {
	# Comments stripped: the rationale above names the commands in prose.
	local body
	body="$(grep -v '^[[:space:]]*#' "$SCRIPT")"
	local n
	n=$(grep -cE 'timeout [0-9]+ flatpak install --system --noninteractive' <<<"$body")
	[ "$n" -eq 2 ] || {
		echo "FAIL: expected 2 bounded flatpak installs, found ${n}." >&2
		echo "      An unbounded flatpak install in a tacklebox customize" >&2
		echo "      script hangs the whole ISO build with no output when its" >&2
		echo "      fetch stalls (grouper:cosmic, run 31144135208)." >&2
		return 1
	}
	# And no unbounded ones remain.
	! grep -qE '^[[:space:]]*flatpak install' <<<"$body"
}

@test "the network remote-add and the release curls carry deadlines" {
	local body
	# Fold backslash continuations first: the remote-add command and its URL
	# live on separate source lines, so a per-line grep can never see both.
	body="$(sed ':a;/\\$/{N;s/\\\n//;ba}' "$SCRIPT" | grep -v '^[[:space:]]*#')"
	# The tunaos.org remote-add fetches over the network; the file-based one
	# two lines up needs no bound and must not be forced to carry one.
	grep -qE 'timeout [0-9]+ flatpak remote-add.*tunaos\.org' <<<"$body"
	# Every curl in the script must bound the transfer, not just retry it:
	# --retry without --max-time retries only failures, not stalls.
	local unbounded
	unbounded=$(grep -E 'curl ' <<<"$body" | grep -v -- '--max-time' || true)
	[ -z "$unbounded" ] || {
		echo "FAIL: curl without --max-time can stall forever:" >&2
		echo "$unbounded" >&2
		return 1
	}
}
