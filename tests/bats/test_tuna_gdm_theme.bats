#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/build_scripts/desktop/tuna-gdm-theme.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}/usr/share/gnome-shell" "${ROOT}/usr/bin" \
    "${ROOT}/usr/share/tunaos"
  printf 'unchanged package resource\n' >"${ROOT}/usr/share/gnome-shell/gnome-shell-theme.gresource"
  printf "TUNAOS_ACCENT='#1793D1'\n" >"${ROOT}/usr/share/tunaos/identity.env"
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

  local drop_in="${ROOT}/etc/systemd/user/org.gnome.Shell@gdm.service.d/tunaos-gdm-theme.conf"
  [ -f "$drop_in" ]
  grep -Fqx '[Service]' "$drop_in"
  grep -Fqx 'Environment=G_RESOURCE_OVERLAYS=/org/gnome/shell/theme=/usr/share/tunaos/gdm-theme' "$drop_in"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(grep -Fc 'background-color: #1793D1;' "${ROOT}/usr/share/tunaos/gdm-theme/gnome-shell-dark.css")" -eq 1 ]
}

@test "GDM theme overlay applies only to the greeter shell instance" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ ! -d "${ROOT}/etc/systemd/system/gdm.service.d" ]
  [ ! -d "${ROOT}/etc/systemd/system/gdm3.service.d" ]
  [ ! -e "${ROOT}/usr/share/gdm/greeter/applications/org.gnome.Shell.desktop" ]
  [ ! -e "${ROOT}/usr/share/applications/org.gnome.Shell.desktop" ]
  grep -Fq G_RESOURCE_OVERLAYS \
    "${ROOT}/etc/systemd/user/org.gnome.Shell@gdm.service.d/tunaos-gdm-theme.conf"
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
