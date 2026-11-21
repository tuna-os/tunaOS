#!/usr/bin/env bats
# The DMS greeter's first-boot wallpaper and fallback mark.
#
# bonito:niri's greeter drew two grey bands and DMS's mascot (strict run
# 44851254596). DMS draws that backdrop when <cache dir>/session.json names
# no wallpaper. Zirconium's 99-dms-greeter.conf linked session.json into an
# empty zdots directory, so the link dangled. These fixtures run the real
# setter and check against a root built from the pinned Zirconium snapshot.
# They prove configuration, not pixels.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SET="${REPO_ROOT}/build_scripts/desktop/dms-greeter-set-branding.sh"
  CHECK="${REPO_ROOT}/build_scripts/checks/verify-dms-greeter.sh"
  ZIRCONIUM="${REPO_ROOT}/_upstream-snapshots/zirconium/mkosi.extra"
  ROOT="${BATS_TEST_TMPDIR}/root"
  WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
  LOGO=/usr/share/pixmaps/tunaos.svg
  TREE="${ROOT}/usr/share/quickshell/dms-greeter"
}

_code() { grep -v '^[[:space:]]*#' "$1"; }

# The image after install-zirconium.sh, the dnf transaction and the pinned
# DMS v1.6.3 QML payload, before any branding step.
_stock_root() {
  mkdir -p "${ROOT}/etc/greetd" "${ROOT}/usr/lib/tmpfiles.d" \
    "${ROOT}/usr/share/backgrounds/tunaos" "${ROOT}/usr/share/pixmaps" "${TREE}/assets"
  cp "${ZIRCONIUM}/usr/share/factory/etc/greetd/config.toml" "${ROOT}/etc/greetd/config.toml"
  cp "${REPO_ROOT}/system_files/usr/share/backgrounds/tunaos/bonito.jpg" "${ROOT}${WALLPAPER}"
  cp "${REPO_ROOT}/system_files/usr/share/tunaos/logos/bonito.svg" "${ROOT}${LOGO}"
  echo '// DMSGreeter shell' >"${TREE}/shell.qml"
  echo '<svg><!-- DMS mascot --></svg>' >"${TREE}/assets/danklogonormal.svg"
}

_with_upstream_tmpfiles() {
  cp "${ZIRCONIUM}/usr/lib/tmpfiles.d/99-dms-greeter.conf" "${ROOT}/usr/lib/tmpfiles.d/99-dms-greeter.conf"
}

@test "the stock Zirconium greeter state fails: dangling session.json and the DMS mascot" {
  # Falsification: make tmpfiles_entry print nothing, or skip the existence
  # test on its target, and this stock root reports OK.
  _stock_root
  _with_upstream_tmpfiles
  run "$CHECK" bonito --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"zdots/private_dot_local/state/DankMaterialShell/session.json, which does not exist"* ]]
  [[ "$output" == *"danklogonormal.svg is not ${LOGO}"* ]]
  [[ "$output" == *"TUNAOS_DMS_GREETER_FAIL variant=bonito failures=2 mode=build"* ]]
}

@test "the setter makes the greeter resolve the variant wallpaper and mark" {
  _stock_root
  run "$SET" "$ROOT"
  [ "$status" -eq 0 ]
  [ "$(readlink "${TREE}/assets/danklogonormal.svg")" = "$LOGO" ]
  grep -qx "L /var/cache/dms-greeter/session.json - - - - /usr/share/tunaos/dms-greeter/session.json" \
    "${ROOT}/usr/lib/tmpfiles.d/tunaos-dms-greeter.conf"
  grep -qF "\"wallpaperPath\": \"${WALLPAPER}\"" "${ROOT}/usr/share/tunaos/dms-greeter/session.json"

  run "$CHECK" bonito --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_DMS_GREETER_OK variant=bonito wallpaper=${WALLPAPER} logo=${LOGO} session=tmpfiles:L:/usr/share/tunaos/dms-greeter/session.json mode=build"* ]]
}

@test "the setter is idempotent" {
  _stock_root
  "$SET" "$ROOT" >/dev/null
  "$SET" "$ROOT" >/dev/null
  run "$CHECK" bonito --root "$ROOT"
  [ "$status" -eq 0 ]
}

@test "an earlier-named tmpfiles entry for session.json wins, as in systemd-tmpfiles" {
  # Falsification: process tmpfiles.d files in directory order instead of by
  # name, and tunaos-dms-greeter.conf would win here and the check would pass.
  _stock_root
  "$SET" "$ROOT" >/dev/null
  _with_upstream_tmpfiles
  run "$CHECK" bonito --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"comes from tmpfiles:L:/usr/share/zirconium/zdots/"* ]]
}

@test "a session.json naming another wallpaper fails" {
  _stock_root
  "$SET" "$ROOT" >/dev/null
  sed -i 's#tunaos/tunaos-default.jpg#dms/default.jpg#' "${ROOT}/usr/share/tunaos/dms-greeter/session.json"
  run "$CHECK" bonito --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"wallpaperPath='/usr/share/backgrounds/dms/default.jpg', expected ${WALLPAPER}"* ]]
}

@test "runtime mode reads the cache file the greeter opens" {
  _stock_root
  "$SET" "$ROOT" >/dev/null
  mkdir -p "${ROOT}/var/cache/dms-greeter"
  # A dangling link left by the old Zirconium tmpfiles entry.
  ln -s /usr/share/zirconium/zdots/private_dot_local/state/DankMaterialShell/session.json \
    "${ROOT}/var/cache/dms-greeter/session.json"
  run "$CHECK" bonito --runtime --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"TUNAOS_DMS_GREETER_FAIL variant=bonito failures=1 mode=runtime"* ]]

  rm "${ROOT}/var/cache/dms-greeter/session.json"
  cp "${ROOT}/usr/share/tunaos/dms-greeter/session.json" "${ROOT}/var/cache/dms-greeter/session.json"
  run "$CHECK" bonito --runtime --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"wallpaper=${WALLPAPER} logo=${LOGO}"*"mode=runtime"* ]]
}

@test "a greetd that runs gtkgreet is not applicable to the setter or the check" {
  mkdir -p "${ROOT}/etc/greetd"
  printf '[default_session]\ncommand = "cage -s -- gtkgreet"\nuser = "greetd"\n' >"${ROOT}/etc/greetd/config.toml"
  run "$SET" "$ROOT"
  [ "$status" -eq 0 ]
  [ ! -e "${ROOT}/usr/lib/tmpfiles.d/tunaos-dms-greeter.conf" ]
  run "$CHECK" marlin --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_DMS_GREETER_SKIP variant=marlin reason=greeter-not-dms greeter=cage mode=build"* ]]
}

@test "both desktop install call sites run the setter, then the check" {
  local f
  for f in build_scripts/desktop/install-desktop.sh build_scripts/desktop/configure-desktop-runtime.sh; do
    _code "${REPO_ROOT}/${f}" | grep -qF 'build_scripts/desktop/dms-greeter-set-branding.sh'
    _code "${REPO_ROOT}/${f}" | grep -qF 'build_scripts/checks/verify-dms-greeter.sh'
    _code "${REPO_ROOT}/${f}" | grep -qF 'ExecStart=-/usr/libexec/tunaos/verify-dms-greeter'
    [ "$(_code "${REPO_ROOT}/${f}" | grep -nF 'dms-greeter-set-branding.sh' | head -1 | cut -d: -f1)" -lt \
      "$(_code "${REPO_ROOT}/${f}" | grep -nF 'checks/verify-dms-greeter.sh' | head -1 | cut -d: -f1)" ]
  done
}

@test "install-zirconium.sh does not install the dangling greeter tmpfiles entry" {
  ! _code "${REPO_ROOT}/build_scripts/install-zirconium.sh" | grep -qF 'tmpfiles.d/99-dms-greeter.conf'
}

@test "the setter and the check pass shellcheck" {
  command -v shellcheck >/dev/null || skip "shellcheck not installed"
  run shellcheck --severity=warning "$SET" "$CHECK"
  [ "$status" -eq 0 ]
}
