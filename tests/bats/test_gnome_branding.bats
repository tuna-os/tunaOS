#!/usr/bin/env bats
# Execute the writer and verifier against real compiled dconf databases. These
# fixtures establish configuration behavior, never published-image visual proof.
setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SET="${REPO_ROOT}/build_scripts/desktop/gnome-set-branding.sh"
  CHECK="${REPO_ROOT}/build_scripts/checks/verify-branding-gnome.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "$ROOT"
}

_compile() {
  dconf compile "${ROOT}/etc/dconf/db/local" "${ROOT}/etc/dconf/db/local.d"
  dconf compile "${ROOT}/etc/dconf/db/gdm" "${ROOT}/etc/dconf/db/gdm.d"
}

_fixture() {
  command -v dconf >/dev/null || skip "dconf required for real compiled-settings fixture"
  mkdir -p "${ROOT}/usr/share/backgrounds/tunaos" "${ROOT}/usr/share/pixmaps" \
    "${ROOT}/usr/share/tunaos/lettermarks"
  cp "${REPO_ROOT}/system_files/usr/share/tunaos/lettermarks/marlin.svg" "${ROOT}/usr/share/tunaos/lettermarks/marlin.svg"
  cp "${ROOT}/usr/share/tunaos/lettermarks/marlin.svg" "${ROOT}/usr/share/pixmaps/tunaos-lettermark.svg"
  cp "${REPO_ROOT}/system_files/usr/share/backgrounds/tunaos/marlin.jpg" "${ROOT}/usr/share/backgrounds/tunaos/marlin.jpg"
  cp "${ROOT}/usr/share/backgrounds/tunaos/marlin.jpg" "${ROOT}/usr/share/backgrounds/tunaos/tunaos-default.jpg"
  printf "TUNAOS_VARIANT='marlin'\n" >"${ROOT}/usr/share/tunaos/identity.env"
  "$SET" "$ROOT" >/dev/null
  _compile
}

_check() {
  run env TUNAOS_DCONF_DB="${ROOT}/etc/dconf/db" TUNAOS_BRANDING_ROOT="$ROOT" \
    "$CHECK" "${1:-marlin}"
}

@test "writer sets light and dark wallpaper defaults without locks" {
  "$SET" "$ROOT" >/dev/null
  grep -qx "picture-uri='file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'" "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding"
  grep -qx "picture-uri-dark='file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'" "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding"
  [ -z "$(find "${ROOT}/etc/dconf/db" -name locks -print -quit)" ]
}

@test "writer routes GDM wordmark through its own profile and remains idempotent" {
  _fixture
  "$SET" "$ROOT" >/dev/null
  [ "$(grep -cx system-db:gdm "${ROOT}/etc/dconf/profile/gdm")" -eq 1 ]
  [ "$(grep -cx system-db:local "${ROOT}/etc/dconf/profile/user")" -eq 1 ]
  _compile
  _check
  [ "$status" -eq 0 ]
  [[ "$output" == *"scope=compiled-defaults rendered=not-run existing_user=not-modified"* ]]
}

@test "writer preserves packaged GDM profile defaults with our database before fallback" {
  mkdir -p "${ROOT}/usr/share/dconf/profile"
  printf 'user-db:user\nfile-db:/usr/share/gdm/greeter-dconf-defaults\n' >"${ROOT}/usr/share/dconf/profile/gdm"
  "$SET" "$ROOT" >/dev/null
  [ "$(cat "${ROOT}/etc/dconf/profile/gdm")" = "$(printf 'user-db:user\nsystem-db:gdm\nfile-db:/usr/share/gdm/greeter-dconf-defaults')" ]
}

@test "canonical compiled consumers pass without requiring writer keyfile names" {
  _fixture
  mv "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding" "${ROOT}/etc/dconf/db/local.d/90-alternative"
  mv "${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding" "${ROOT}/etc/dconf/db/gdm.d/90-alternative"
  _compile
  _check
  [ "$status" -eq 0 ]
}

@test "compiled logo rejects another variant's bytes at an existing canonical alias" {
  _fixture
  cp "${REPO_ROOT}/system_files/usr/share/tunaos/lettermarks/yellowfin.svg" "${ROOT}/usr/share/pixmaps/tunaos-lettermark.svg"
  _check
  [ "$status" -ne 0 ]
  [[ "$output" == *"login-screen-logo bytes differ from canonical"* ]]
}

@test "correct shared asset bytes remain valid at a different consumer path" {
  _fixture
  cp "${ROOT}/usr/share/tunaos/lettermarks/marlin.svg" "${ROOT}/usr/share/pixmaps/shared.svg"
  printf "[org/gnome/login-screen]\nlogo='/usr/share/pixmaps/shared.svg'\n" >"${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding"
  _compile
  _check
  [ "$status" -eq 0 ]
}

@test "stale compiled GDM settings fail even after keyfile is corrected" {
  _fixture
  printf "[org/gnome/login-screen]\nlogo='/usr/share/pixmaps/wrong.svg'\n" >"${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding"
  cp "${REPO_ROOT}/system_files/usr/share/tunaos/lettermarks/yellowfin.svg" "${ROOT}/usr/share/pixmaps/wrong.svg"
  _compile
  "$SET" "$ROOT" >/dev/null
  _check
  [ "$status" -ne 0 ]
  [[ "$output" == *"login-screen-logo bytes differ from canonical"* ]]
}

@test "GDM profile disconnected from compiled database fails" {
  _fixture
  printf 'user-db:user\n' >"${ROOT}/etc/dconf/profile/gdm"
  _check
  [ "$status" -ne 0 ]
  [[ "$output" == *"profile does not consume system-db:gdm"* ]]
}

@test "missing compiled database fails rather than accepting keyfiles" {
  _fixture
  rm "${ROOT}/etc/dconf/db/local"
  _check
  [ "$status" -ne 0 ]
  [[ "$output" == *"run dconf update"* ]]
}

@test "installed but unused wallpaper and stale dark defaults fail" {
  _fixture
  printf "[org/gnome/desktop/background]\npicture-uri='file:///unused.jpg'\npicture-uri-dark='file:///unused.jpg'\n" >"${ROOT}/etc/dconf/db/local.d/10-tunaos-branding"
  _compile
  "$SET" "$ROOT" >/dev/null
  _check
  [ "$status" -ne 0 ]
  [[ "$output" == *"compiled picture-uri="* ]]
  [[ "$output" == *"compiled picture-uri-dark="* ]]
}

@test "sibling wallpaper at the default alias fails" {
  _fixture
  cp "${REPO_ROOT}/system_files/usr/share/backgrounds/tunaos/yellowfin.jpg" "${ROOT}/usr/share/backgrounds/tunaos/tunaos-default.jpg"
  _check
  [ "$status" -ne 0 ]
  [[ "$output" == *"picture-uri bytes differ from canonical"* ]]
}

@test "publish or display name cannot substitute for canonical variant identity" {
  _fixture
  printf "TUNAOS_VARIANT='bonito-rawhide'\n" >"${ROOT}/usr/share/tunaos/identity.env"
  _check bonito
  [ "$status" -ne 0 ]
  [[ "$output" == *"canonical variant=bonito-rawhide does not match requested variant=bonito"* ]]
}

@test "fresh default readback preserves an existing user's explicit wallpaper" {
  _fixture
  command -v dbus-run-session >/dev/null || skip "dbus-run-session required for real user preference"
  # Writing a user preference needs gsettings with the dconf GIO module. Use
  # the gsettings next to the dconf binary: a separate GLib (for example
  # Homebrew's) has no dconf module and keeps the value in memory only.
  local gsettings
  gsettings="$(dirname "$(command -v dconf)")/gsettings"
  [ -x "$gsettings" ] || skip "gsettings from the dconf installation required"
  command -v glib-compile-schemas >/dev/null || skip "glib-compile-schemas required"
  mkdir -p "${ROOT}/schemas"
  cat >"${ROOT}/schemas/branding.gschema.xml" <<'XML'
<schemalist>
  <schema id="org.gnome.desktop.background" path="/org/gnome/desktop/background/">
    <key name="picture-uri" type="s"><default>''</default></key>
  </schema>
</schemalist>
XML
  glib-compile-schemas "${ROOT}/schemas"
  local user="${ROOT}/existing-user"
  mkdir -p "${user}/config"
  env HOME="$user" XDG_CONFIG_HOME="${user}/config" DCONF_PROFILE="${ROOT}/etc/dconf/profile/user" \
    GSETTINGS_BACKEND=dconf GSETTINGS_SCHEMA_DIR="${ROOT}/schemas" dbus-run-session -- \
    "$gsettings" set org.gnome.desktop.background picture-uri 'file:///chosen-by-user.jpg'
  [ -s "${user}/config/dconf/user" ] || skip "gsettings did not write through the dconf backend"
  local before
  before="$(sha256sum "${user}/config/dconf/user")"
  HOME="$user" XDG_CONFIG_HOME="${user}/config" _check
  [ "$status" -eq 0 ]
  [ "$(sha256sum "${user}/config/dconf/user")" = "$before" ]
}

@test "compiled readback needs no session bus or gsettings" {
  _fixture
  # The build and the systemd unit have no session bus. A gsettings that
  # fails on every call proves that the check does not depend on it.
  mkdir -p "${BATS_TEST_TMPDIR}/bin"
  printf '#!/bin/sh\necho "gsettings must not run" >&2\nexit 99\n' >"${BATS_TEST_TMPDIR}/bin/gsettings"
  chmod +x "${BATS_TEST_TMPDIR}/bin/gsettings"
  run env -u DISPLAY -u WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent/bus \
    PATH="${BATS_TEST_TMPDIR}/bin:${PATH}" TUNAOS_DCONF_DB="${ROOT}/etc/dconf/db" \
    TUNAOS_BRANDING_ROOT="$ROOT" "$CHECK" marlin
  [ "$status" -eq 0 ]
  [[ "$output" != *"gsettings must not run"* ]]
  [[ "$output" == *"TUNAOS_BRANDING_GNOME_OK variant=marlin"* ]]
}

@test "writer names the canonical lettermark alias, never the square mark" {
  "$SET" "$ROOT" >/dev/null
  grep -qx "logo='/usr/share/pixmaps/tunaos-lettermark.svg'" "${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding"
  ! grep -q 'pixmaps/tunaos.svg' "${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding"
}

@test "missing canonical GNOME wallpaper fails with an explicit message" {
  _fixture
  rm "${ROOT}/usr/share/backgrounds/tunaos/marlin.jpg"
  _check
  [ "$status" -ne 0 ]
  [[ "$output" == *"no canonical wallpaper for variant=marlin desktop=gnome"* ]]
  [[ "$output" != *"canonical picture-uri asset missing"* ]]
}

@test "Tuna integration changes only the greeter and does not claim wallpaper consumption" {
  _fixture
  rm "${ROOT}/etc/dconf/db/local"
  rm -r "${ROOT}/etc/dconf/db/local.d"
  rm "${ROOT}/etc/dconf/profile/user"
  TUNAOS_BRANDING_DESKTOP=tuna "$SET" "$ROOT" >/dev/null
  [ ! -e "${ROOT}/etc/dconf/db/local.d" ]
  [ ! -e "${ROOT}/etc/dconf/profile/user" ]
  dconf compile "${ROOT}/etc/dconf/db/gdm" "${ROOT}/etc/dconf/db/gdm.d"
  TUNAOS_BRANDING_DESKTOP=tuna _check
  [ "$status" -eq 0 ]
  [[ "$output" == *"scope=compiled-greeter rendered=not-run existing_user=not-modified wallpaper=not-run"* ]]
}


# Existing os-release identity coverage, independent of the consumer fixtures.
@test "the branding contract checks all four os-release URLs" {
  grep -q 'for field in HOME_URL DOCUMENTATION_URL SUPPORT_URL BUG_REPORT_URL' \
    "${REPO_ROOT}/build_scripts/checks/verify-branding.sh"
}

@test "accent is written to the gdm database so GNOME Initial Setup picks it up" {
  mkdir -p "${ROOT}/usr/share/tunaos"
  printf "TUNAOS_GNOME_ACCENT='orange'\n" >"${ROOT}/usr/share/tunaos/identity.env"
  "$SET" "$ROOT" >/dev/null
  grep -qx "accent-color='orange'" "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding"
  grep -qx "accent-color='orange'" "${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding"
}
