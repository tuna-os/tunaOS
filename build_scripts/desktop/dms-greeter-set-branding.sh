#!/usr/bin/env bash
# Give the DMS greeter the variant wallpaper and mark before anyone logs in.
#
# The DMS greeter (dms-greeter, DankMaterialShell) reads its wallpaper from
# <cache dir>/session.json, key wallpaperPath. The cache dir is the
# --cache-dir in greetd's command, /var/cache/dms-greeter by default. With
# no wallpaper there it draws DankBackdrop: two grey bands and DMS's mascot,
# assets/danklogonormal.svg, in the bottom-left corner (DankMaterialShell
# v1.6.3 quickshell/Widgets/DankBackdrop.qml:52).
#
# Zirconium's 99-dms-greeter.conf linked session.json into
# /usr/share/zirconium/zdots, which install-zirconium.sh leaves empty. Every
# link dangled, so every first boot showed the mascot (bonito:niri, strict
# run 44851254596).
#
# This script:
#   - writes /usr/share/tunaos/dms-greeter/session.json naming the variant
#     wallpaper;
#   - links <cache dir>/session.json to it at boot (tmpfiles L, which leaves
#     a file from `dms greeter sync` alone);
#   - points the greeter tree's danklogonormal.svg at the variant mark, so
#     the fallback backdrop cannot show the DMS mascot.
#
# No-op when greetd does not launch dms-greeter (gtkgreet on Arch and
# openSUSE). verify-dms-greeter.sh asserts the result. Idempotent.
#
#   dms-greeter-set-branding.sh           # the running build root
#   dms-greeter-set-branding.sh <root>    # write under <root> instead (tests)

set -euo pipefail

root="${1:-}"
WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
LOGO=/usr/share/pixmaps/tunaos.svg
DEFAULTS=/usr/share/tunaos/dms-greeter/session.json
TMPFILES=/usr/lib/tmpfiles.d/tunaos-dms-greeter.conf
greetd="${TUNAOS_GREETD_CONFIG:-${root}/etc/greetd/config.toml}"

command_line="$(sed -n '/^\[default_session\]/,/^\[/{s/^[[:space:]]*command[[:space:]]*=[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p}' "$greetd" 2>/dev/null | head -1 || true)"
if [[ "$command_line" != *dms-greeter* ]]; then
	echo "DMS greeter branding: not applicable (greetd command: ${command_line:-none})"
	exit 0
fi

if [[ -z "$root" && ! -e "$WALLPAPER" ]]; then
	echo "ERROR: ${WALLPAPER} is missing; system_files should have placed it." >&2
	exit 1
fi

cache_dir=/var/cache/dms-greeter
read -ra argv <<<"$command_line"
for ((i = 0; i < ${#argv[@]} - 1; i++)); do
	[[ "${argv[i]}" == --cache-dir ]] && cache_dir="${argv[i + 1]}"
done

# configVersion 5 is the current session schema; an older value makes the
# greeter run its migrations over this file.
install -d -m0755 "${root}$(dirname "$DEFAULTS")"
cat >"${root}${DEFAULTS}" <<JSON
{
  "configVersion": 5,
  "wallpaperPath": "${WALLPAPER}",
  "perMonitorWallpaper": false,
  "perModeWallpaper": false
}
JSON
chmod 0644 "${root}${DEFAULTS}"

install -d -m0755 "${root}$(dirname "$TMPFILES")"
cat >"${root}${TMPFILES}" <<EOF
# Written by build_scripts/desktop/dms-greeter-set-branding.sh.
# The greeter's first-boot wallpaper; a later \`dms greeter sync\` replaces it.
L ${cache_dir}/session.json - - - - ${DEFAULTS}
EOF
chmod 0644 "${root}${TMPFILES}"
echo "DMS greeter wallpaper: ${cache_dir}/session.json -> ${DEFAULTS} (wallpaperPath=${WALLPAPER})"

for tree in "${root}/usr/share/quickshell/dms-greeter" "${root}/etc/xdg/quickshell/dms-greeter"; do
	[[ -f "${tree}/assets/danklogonormal.svg" ]] || continue
	ln -sfn "$LOGO" "${tree}/assets/danklogonormal.svg"
	echo "DMS greeter mark: ${tree#"${root}"}/assets/danklogonormal.svg -> ${LOGO}"
done
