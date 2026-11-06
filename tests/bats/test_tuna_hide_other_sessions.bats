#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/build_scripts/desktop/tuna-hide-other-sessions.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}/usr/share/wayland-sessions"
  export TUNAOS_GDM_SESSIONS_ROOT="${ROOT}"
}

@test "hidden sessions leave only Tuna visible" {
  cat >"${ROOT}/usr/share/wayland-sessions/gnome.desktop" <<'DESKTOP'
[Desktop Entry]
Name=GNOME
Exec=gnome-session
Type=Application
DESKTOP
  cat >"${ROOT}/usr/share/wayland-sessions/tuna.desktop" <<'DESKTOP'
[Desktop Entry]
Name=Tuna Desktop
Exec=tuna-session
Type=Application
DESKTOP
  cat >"${ROOT}/usr/share/wayland-sessions/roost.desktop" <<'DESKTOP'
[Desktop Entry]
Name=Roost
NoDisplay=true
DESKTOP
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'NoDisplay=true' "${ROOT}/usr/share/wayland-sessions/gnome.desktop"
  run grep -Fxq 'NoDisplay=true' "${ROOT}/usr/share/wayland-sessions/tuna.desktop"
  [ "$status" -ne 0 ]
  [ "$(grep -c '^NoDisplay=true$' "${ROOT}/usr/share/wayland-sessions/gnome.desktop")" -eq 1 ]
}

@test "hiding is idempotent" {
  printf '[Desktop Entry]\nNoDisplay=true\n' >"${ROOT}/usr/share/wayland-sessions/gnome.desktop"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(grep -c '^NoDisplay=true' "${ROOT}/usr/share/wayland-sessions/gnome.desktop")" -eq 1 ]
}
