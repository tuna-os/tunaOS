#!/usr/bin/env bats
# Pantheon must not be mistaken for GNOME.
#
# customize-live.sh's detection had no pantheon branch and DESKTOP defaults to
# "gnome", so gurnard:pantheon ran desktop-gnome.sh — which writes GDM
# autologin. MEASURED on the published gurnard-pantheon ISO:
#
#   /etc/gdm/custom.conf      -> present, AutomaticLogin=liveuser
#   gdm/gdm3/sddm/greetd      -> NONE shipped
#   lightdm                   -> the only DM, and display-manager.service
#                                points at it
#   /etc/lightdm/...          -> no autologin anywhere
#   liveuser                  -> exists
#
# The account was fine; nothing logged it in. The live session never started
# and the harness saw a black screen (stddev=0 on every frame, three runs,
# 420s settle), with no sshd on production media to explain itself.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CUSTOMIZE="${REPO_ROOT}/live-iso/common/src/customize-live.sh"
ADAPTER="${REPO_ROOT}/live-iso/common/src/desktop-pantheon.sh"

detect() {
  # Drive the real detection block against a fake session root.
  local root="$1"
  TUNA_SESSION_ROOT="$root" TUNA_DETECT_ONLY=1 bash "$CUSTOMIZE" 2>/dev/null |
    grep '^DETECTED ' || true
}

@test "a pantheon wayland image is detected as pantheon, not gnome" {
  local root="${BATS_TEST_TMPDIR}/p1"
  mkdir -p "${root}/usr/share/wayland-sessions"
  touch "${root}/usr/share/wayland-sessions/pantheon-wayland.desktop"
  run detect "$root"
  [[ "$output" == *"DETECTED pantheon"* ]]
}

@test "an X11-only pantheon image is detected too" {
  local root="${BATS_TEST_TMPDIR}/p2"
  mkdir -p "${root}/usr/share/xsessions"
  touch "${root}/usr/share/xsessions/pantheon.desktop"
  run detect "$root"
  [[ "$output" == *"DETECTED pantheon"* ]]
}

@test "an image with no known session still falls back to gnome" {
  # The default must stay put — this fix adds a branch, it does not change
  # what happens for images the detection genuinely cannot identify.
  local root="${BATS_TEST_TMPDIR}/p3"
  mkdir -p "${root}/usr/share"
  run detect "$root"
  [[ "$output" == *"DETECTED gnome"* ]]
}

@test "pantheon does not take a display manager it does not ship" {
  # The whole bug: GDM config written into an image whose only DM is lightdm.
  # Check the CODE, not the prose -- the header deliberately explains the gdm
  # mistake, and a test that forbids naming it would forbid documenting it.
  grep -q 'lightdm' "$ADAPTER"
  local code
  code="$(grep -vE '^[[:space:]]*#' "$ADAPTER")"
  ! echo "$code" | grep -qE '/etc/gdm|gdm3'
}

@test "the adapter configures lightdm autologin for liveuser" {
  grep -q 'autologin-user=liveuser' "$ADAPTER"
  grep -q 'autologin-user-timeout=0' "$ADAPTER"
  grep -q 'lightdm.conf.d' "$ADAPTER"
}

@test "autologin-session names a session file the image actually has" {
  # Pointing autologin at a session that does not exist reproduces the same
  # black screen by a different route, so the adapter checks before choosing.
  grep -q 'pantheon-wayland.desktop' "$ADAPTER"
  grep -q 'xsessions/pantheon.desktop' "$ADAPTER"
}

@test "the installer is launched at session start" {
  grep -q 'org.tunaos.installer-live.desktop' "$ADAPTER"
  grep -q 'org.bootcinstaller.Installer' "$ADAPTER"
}

@test "pantheon maps to the upstream installer, like gnome" {
  grep -q 'pantheon) INSTALLER_APP="org.bootcinstaller.Installer"' "$CUSTOMIZE"
}

@test "the adapter is executable and lints" {
  [ -x "$ADAPTER" ]
  bash -n "$ADAPTER"
}
