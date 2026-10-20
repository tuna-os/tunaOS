#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/build_scripts/desktop/tuna-gdm-theme.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}/usr/share/gnome-shell" "${ROOT}/usr/bin" \
    "${ROOT}/usr/share/tunaos" "${ROOT}/usr/share/applications"
  printf 'unchanged package resource\n' >"${ROOT}/usr/share/gnome-shell/gnome-shell-theme.gresource"
  printf "TUNAOS_ACCENT='#1793D1'\n" >"${ROOT}/usr/share/tunaos/identity.env"
  cat >"${ROOT}/usr/share/applications/org.gnome.Shell.desktop" <<'DESKTOP'
[Desktop Entry]
Name=GNOME Shell
Exec=/usr/bin/gnome-shell --mode=gdm
Type=Application
DESKTOP
  export TUNAOS_GDM_THEME_ROOT="${ROOT}"
  export PATH="${ROOT}/usr/bin:${PATH}"
  cat >"${ROOT}/usr/bin/gjs" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == -c ]] || exit 2
[[ "$TUNAOS_GRESOURCE_FILE" == "${TUNAOS_GDM_THEME_ROOT}/usr/share/gnome-shell/gnome-shell-theme.gresource" ]] || exit 2
case "$TUNAOS_GRESOURCE_PATH" in
  /org/gnome/shell/theme/gnome-shell-dark.css|/org/gnome/shell/theme/gnome-shell-light.css|/org/gnome/shell/theme/gnome-shell-high-contrast.css) ;;
  *) exit 2 ;;
esac
[[ "${GDM_THEME_MISSING_RESOURCE:-}" != "$TUNAOS_GRESOURCE_PATH" ]] || exit 1
printf '/* packaged upstream stylesheet: %s */\n' "$TUNAOS_GRESOURCE_PATH"
MOCK
  chmod +x "${ROOT}/usr/bin/gjs"
}

@test "GDM theme keeps upstream styles and applies the variant accent in every stylesheet" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]

  for stylesheet in gnome-shell-dark.css gnome-shell-light.css gnome-shell-high-contrast.css; do
    local path="${ROOT}/usr/share/tunaos/gdm-theme/${stylesheet}"
    [ -f "$path" ]
    grep -Fq "/* packaged upstream stylesheet: /org/gnome/shell/theme/${stylesheet} */" "$path"
    grep -Fqx '  background-color: #1793D1;' "$path"
    [ "$(grep -Fc 'background-color: #1793D1;' "$path")" -eq 1 ]
  done

  [ "$(cat "${ROOT}/usr/share/gnome-shell/gnome-shell-theme.gresource")" = "unchanged package resource" ]
  grep -Fqx 'Exec=/usr/bin/gnome-shell --mode=gdm' \
    "${ROOT}/usr/share/applications/org.gnome.Shell.desktop"
  grep -Fqx 'Exec=env G_RESOURCE_OVERLAYS=/org/gnome/shell/theme=/usr/share/tunaos/gdm-theme /usr/bin/gnome-shell --mode=gdm' \
    "${ROOT}/usr/share/gdm/greeter/applications/org.gnome.Shell.desktop"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(grep -Fc 'background-color: #1793D1;' "${ROOT}/usr/share/tunaos/gdm-theme/gnome-shell-dark.css")" -eq 1 ]
}

@test "GDM theme does not set the overlay on the daemon or regular user sessions" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ ! -d "${ROOT}/etc/systemd/system/gdm.service.d" ]
  [ ! -d "${ROOT}/etc/systemd/system/gdm3.service.d" ]
  run grep -Fq G_RESOURCE_OVERLAYS "${ROOT}/usr/share/applications/org.gnome.Shell.desktop"
  [ "$status" -ne 0 ]
  grep -Fq G_RESOURCE_OVERLAYS \
    "${ROOT}/usr/share/gdm/greeter/applications/org.gnome.Shell.desktop"
}

@test "GDM theme keeps the last complete theme if resource extraction fails" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]

  printf "TUNAOS_ACCENT='#E95420'\n" >"${ROOT}/usr/share/tunaos/identity.env"
  export GDM_THEME_MISSING_RESOURCE=/org/gnome/shell/theme/gnome-shell-high-contrast.css
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  for stylesheet in gnome-shell-dark.css gnome-shell-light.css gnome-shell-high-contrast.css; do
    grep -Fqx '  background-color: #1793D1;' "${ROOT}/usr/share/tunaos/gdm-theme/${stylesheet}"
    run grep -Fq '#E95420' "${ROOT}/usr/share/tunaos/gdm-theme/${stylesheet}"
    [ "$status" -ne 0 ]
  done
}
