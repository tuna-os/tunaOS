#!/usr/bin/env bats
# COSMIC, XFCE and Pantheon, and their greeters, must apply the variant
# wallpaper by default (docs/BRANDING.md, Application). Each case builds a
# temporary root with what the upstream packages ship, runs
# verify-desktop-wallpaper.sh on it, then the <desktop>-set-branding.sh fix,
# then the check again.
#
# Falsification: each "upstream" case asserts the check FAILS on the package
# defaults (cosmic-bg's nebula, xfdesktop's compiled default, Fedora's greeter
# background, elementary's :Pantheon override). Remove a fix from a
# set-branding script and its "after" case fails the same way.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  CHECK="${REPO_ROOT}/build_scripts/checks/verify-desktop-wallpaper.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  WALL=/usr/share/backgrounds/tunaos/tunaos-default.jpg
  mkdir -p "${ROOT}/usr/share/backgrounds/tunaos"
  echo jpeg >"${ROOT}${WALL}"
}

# The display manager the image boots, as systemctl enable leaves it.
_dm() {
  mkdir -p "${ROOT}/etc/systemd/system"
  ln -sfn "/usr/lib/systemd/system/$1.service" "${ROOT}/etc/systemd/system/display-manager.service"
}

_cosmic_upstream() {
  local id
  for id in com.system76.CosmicBackground com.system76.CosmicBackground.Dark com.system76.CosmicBackground.Light; do
    mkdir -p "${ROOT}/usr/share/cosmic/${id}/v1"
    printf '(\n    output: "all",\n    source: Path("/usr/share/backgrounds/cosmic/system76-cosmic-dark.png"),\n    filter_by_theme: false,\n)\n' \
      >"${ROOT}/usr/share/cosmic/${id}/v1/all"
  done
  _dm cosmic-greeter
}

@test "cosmic: the check fails on cosmic-bg's stock defaults" {
  _cosmic_upstream
  run "$CHECK" cosmic --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"TUNAOS_DESKTOP_WALLPAPER_FAIL desktop=cosmic"* ]]
  [[ "$output" == *"system76-cosmic-dark.png"* ]]
}

@test "cosmic: set-branding covers the shared and both per-mode config ids" {
  _cosmic_upstream
  "${REPO_ROOT}/build_scripts/desktop/cosmic-set-branding.sh" "$ROOT"
  "${REPO_ROOT}/build_scripts/desktop/cosmic-set-branding.sh" "$ROOT"
  run "$CHECK" cosmic --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_DESKTOP_WALLPAPER_OK desktop=cosmic wallpaper=${WALL} greeter=cosmic-greeter greeter_status=open"* ]]
}

@test "cosmic: a per-mode id left at the package default fails" {
  _cosmic_upstream
  "${REPO_ROOT}/build_scripts/desktop/cosmic-set-branding.sh" "$ROOT"
  # cosmic-bg since d6dcfa9 reads .Dark or .Light; the shared id alone is the old fix.
  printf '(\n    output: "all",\n    source: Path("/usr/share/backgrounds/cosmic/system76-cosmic-dark.png"),\n)\n' \
    >"${ROOT}/usr/share/cosmic/com.system76.CosmicBackground.Dark/v1/all"
  run "$CHECK" cosmic --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"com.system76.CosmicBackground.Dark all"* ]]
}

# Fedora's xfdesktop and lightdm-gtk, as measured: DEFAULT_BACKDROP is
# default.jxl, and /etc/lightdm/lightdm-gtk-greeter.conf sets background=.
_xfce_upstream_fedora() {
  mkdir -p "${ROOT}/usr/bin" "${ROOT}/usr/share/backgrounds/images" \
    "${ROOT}/usr/share/lightdm/lightdm.conf.d" "${ROOT}/usr/share/lightdm/lightdm-gtk-greeter.conf.d" \
    "${ROOT}/usr/share/xgreeters" "${ROOT}/etc/lightdm"
  printf '\0/usr/share/locale\0/usr/share/backgrounds/images/default.jxl\0/usr/share/pixmaps/xfdesktop/xfdesktop-fallback-icon.png\0/usr/share/backgrounds/xfce/xfce-stripes.png\0/usr/share/backgrounds/xfce/xfce-teal.png\0/usr/share/backgrounds/xfce/xfce-verticals.png\0' \
    >"${ROOT}/usr/bin/xfdesktop"
  echo fedora >"${ROOT}/usr/share/backgrounds/images/default.jxl"
  printf '[Seat:*]\ngreeter-session=lightdm-gtk-greeter\n' >"${ROOT}/usr/share/lightdm/lightdm.conf.d/60-lightdm-gtk-greeter.conf"
  : >"${ROOT}/usr/share/xgreeters/lightdm-gtk-greeter.desktop"
  cp "${REPO_ROOT}/system_files/usr/share/lightdm/lightdm-gtk-greeter.conf.d/90-tunaos.conf" \
    "${ROOT}/usr/share/lightdm/lightdm-gtk-greeter.conf.d/"
  printf '[greeter]\nbackground=/usr/share/backgrounds/default.jxl\n' >"${ROOT}/etc/lightdm/lightdm-gtk-greeter.conf"
  _dm lightdm
}

@test "xfce: the check fails on xfdesktop's compiled default and Fedora's greeter config" {
  _xfce_upstream_fedora
  run "$CHECK" xfce --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"xfdesktop DEFAULT_BACKDROP: /usr/share/backgrounds/images/default.jxl resolves to /usr/share/backgrounds/images/default.jxl"* ]]
  [[ "$output" == *"lightdm-gtk-greeter background: /usr/share/backgrounds/default.jxl"* ]]
}

@test "xfce: set-branding makes every monitor and the LightDM greeter draw the variant" {
  _xfce_upstream_fedora
  mkdir -p "${ROOT}/etc/xdg/xfce4/xfconf/xfce-perchannel-xml"
  printf '<channel name="xfce4-desktop"><property name="last-image" type="string" value="/usr/share/backgrounds/xfce/xfce-x.svg"/></channel>\n' \
    >"${ROOT}/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml"
  "${REPO_ROOT}/build_scripts/desktop/xfce-set-branding.sh" "$ROOT"
  "${REPO_ROOT}/build_scripts/desktop/xfce-set-branding.sh" "$ROOT"
  [ "$(readlink "${ROOT}/usr/share/backgrounds/images/default.jxl")" = "$WALL" ]
  run "$CHECK" xfce --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_DESKTOP_WALLPAPER_OK desktop=xfce wallpaper=${WALL} greeter=lightdm-gtk-greeter greeter_status=checked"* ]]
}

@test "xfce: Debian's lightdm-greeter alternatives link resolves to the GTK greeter" {
  _xfce_upstream_fedora
  rm "${ROOT}/usr/share/lightdm/lightdm.conf.d/60-lightdm-gtk-greeter.conf"
  printf '[Seat:*]\ngreeter-session=lightdm-greeter\n' >"${ROOT}/usr/share/lightdm/lightdm.conf.d/01_debian.conf"
  mkdir -p "${ROOT}/etc/alternatives"
  ln -s /etc/alternatives/lightdm-greeter "${ROOT}/usr/share/xgreeters/lightdm-greeter.desktop"
  ln -s /usr/share/xgreeters/lightdm-gtk-greeter.desktop "${ROOT}/etc/alternatives/lightdm-greeter"
  "${REPO_ROOT}/build_scripts/desktop/xfce-set-branding.sh" "$ROOT"
  run "$CHECK" xfce --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"greeter=lightdm-gtk-greeter"* ]]
}

@test "xfce: gtkgreet under greetd passes only with the variant stylesheet" {
  _xfce_upstream_fedora
  rm "${ROOT}/etc/systemd/system/display-manager.service"
  mkdir -p "${ROOT}/etc/systemd/system/graphical.target.wants" "${ROOT}/etc/greetd"
  ln -s /usr/lib/systemd/system/greetd.service "${ROOT}/etc/systemd/system/graphical.target.wants/greetd.service"
  printf '[default_session]\ncommand = "/usr/libexec/tunaos/greetd-session"\n' >"${ROOT}/etc/greetd/config.toml"
  printf 'window { background-color: #000; }\n' >"${ROOT}/etc/greetd/gtkgreet.css"
  "${REPO_ROOT}/build_scripts/desktop/xfce-set-branding.sh" "$ROOT"
  run "$CHECK" xfce --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"gtkgreet: /etc/greetd/gtkgreet.css does not draw"* ]]
  printf 'window { background-image: url("file://%s"); }\n' "$WALL" >"${ROOT}/etc/greetd/gtkgreet.css"
  run "$CHECK" xfce --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"greeter=gtkgreet greeter_status=checked"* ]]
}

@test "xfce: an xfdesktop with two candidate default paths stops the build" {
  _xfce_upstream_fedora
  printf '\0/usr/share/backgrounds/images/default.jxl\0/usr/share/backgrounds/other.png\0' >"${ROOT}/usr/bin/xfdesktop"
  run "${REPO_ROOT}/build_scripts/desktop/xfce-set-branding.sh" "$ROOT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"expected one DEFAULT_BACKDROP string"* ]]
}

@test "xfce: where GDM is the display manager (bonito:xfce), it gets the variant lettermark" {
  _xfce_upstream_fedora
  mkdir -p "${ROOT}/usr/lib/systemd/system"
  : >"${ROOT}/usr/lib/systemd/system/gdm.service"
  _dm gdm
  run "$CHECK" xfce --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"gdm: login-screen logo is unset"* ]]
  "${REPO_ROOT}/build_scripts/desktop/xfce-set-branding.sh" "$ROOT"
  [ ! -e "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding" ]
  run "$CHECK" xfce --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"greeter=gdm greeter_status=checked"* ]]
}

# gurnard:pantheon as measured: elementary-default-settings' :Pantheon section,
# io.elementary.greeter under LightDM, and no elementaryos-default file.
_pantheon_upstream() {
  command -v glib-compile-schemas >/dev/null || skip "glib-compile-schemas not installed"
  command -v gsettings >/dev/null || skip "gsettings not installed"
  local s="${ROOT}/usr/share/glib-2.0/schemas"
  mkdir -p "$s" "${ROOT}/usr/share/lightdm/lightdm.conf.d" "${ROOT}/usr/share/xgreeters"
  cat >"${s}/org.gnome.desktop.background.gschema.xml" <<'EOF'
<schemalist>
  <schema id="org.gnome.desktop.background" path="/org/gnome/desktop/background/">
    <key name="picture-uri" type="s"><default>'file:///usr/share/backgrounds/gnome/adwaita-l.jxl'</default></key>
    <key name="picture-uri-dark" type="s"><default>'file:///usr/share/backgrounds/gnome/adwaita-d.jxl'</default></key>
    <key name="picture-options" type="s"><default>'zoom'</default></key>
  </schema>
  <schema id="org.gnome.desktop.screensaver" path="/org/gnome/desktop/screensaver/">
    <key name="picture-uri" type="s"><default>''</default></key>
    <key name="picture-options" type="s"><default>'zoom'</default></key>
  </schema>
</schemalist>
EOF
  printf "[org.gnome.desktop.background:Pantheon]\npicture-uri='file:///usr/share/backgrounds/elementaryos-default'\npicture-uri-dark='file://'\n" \
    >"${s}/default-settings.gschema.override"
  printf '[Seat:*]\ngreeter-session=io.elementary.greeter\n' >"${ROOT}/usr/share/lightdm/lightdm.conf.d/40-io.elementary.greeter.conf"
  : >"${ROOT}/usr/share/xgreeters/io.elementary.greeter.desktop"
  _dm lightdm
}

@test "pantheon: the check fails on elementary's :Pantheon override and the missing greeter fallback" {
  _pantheon_upstream
  glib-compile-schemas "${ROOT}/usr/share/glib-2.0/schemas"
  run "$CHECK" pantheon --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"picture-uri = 'file:///usr/share/backgrounds/elementaryos-default'"* ]]
  [[ "$output" == *"io.elementary.greeter fallback"* ]]
}

@test "pantheon: a plain override section alone still loses to :Pantheon" {
  _pantheon_upstream
  awk '/^\[org.gnome.desktop.background:Pantheon\]/ { skip = 1; next } /^\[/ { skip = 0 } !skip' \
    "${REPO_ROOT}/system_files/usr/share/glib-2.0/schemas/zzzz-tunaos.gschema.override" \
    >"${ROOT}/usr/share/glib-2.0/schemas/zzzz-tunaos.gschema.override"
  "${REPO_ROOT}/build_scripts/desktop/pantheon-set-branding.sh" "$ROOT"
  run "$CHECK" pantheon --root "$ROOT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"elementaryos-default'"* ]]
}

@test "pantheon: the shipped override and set-branding brand the session and greeter" {
  _pantheon_upstream
  cp "${REPO_ROOT}/system_files/usr/share/glib-2.0/schemas/zzzz-tunaos.gschema.override" "${ROOT}/usr/share/glib-2.0/schemas/"
  "${REPO_ROOT}/build_scripts/desktop/pantheon-set-branding.sh" "$ROOT"
  "${REPO_ROOT}/build_scripts/desktop/pantheon-set-branding.sh" "$ROOT"
  run "$CHECK" pantheon --root "$ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_DESKTOP_WALLPAPER_OK desktop=pantheon wallpaper=${WALL} greeter=io.elementary.greeter greeter_status=checked"* ]]
}

@test "both install call sites brand and check COSMIC, XFCE and Pantheon" {
  local install="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  local runtime="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
  grep -qF 'cosmic | xfce)' "$install"
  grep -qF '"${_TD_CTX}/build_scripts/desktop/${_TD_DESKTOP}-set-branding.sh"' "$install"
  grep -qF '"${_TD_CTX}/build_scripts/checks/verify-desktop-wallpaper.sh" "${_TD_DESKTOP}"' "$install"
  grep -qF 'cosmic | xfce | pantheon)' "$runtime"
  grep -qF '"/run/context/build_scripts/desktop/${desktop}-set-branding.sh"' "$runtime"
  grep -qF '/run/context/build_scripts/checks/verify-desktop-wallpaper.sh "$desktop"' "$runtime"
  local d
  for d in cosmic xfce pantheon; do
    [ -x "${REPO_ROOT}/build_scripts/desktop/${d}-set-branding.sh" ]
  done
}
