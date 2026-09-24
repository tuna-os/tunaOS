#!/usr/bin/env bash
# Point COSMIC at the variant's wallpaper instead of the stock nebula.
#
# cosmic-bg reads its system default from
# /usr/share/cosmic/com.system76.CosmicBackground/v1/all, and the cosmic-bg
# package ships that file naming /usr/share/backgrounds/cosmic/*. So this runs
# after the desktop install (both call sites, like gnome-set-branding.sh);
# written any earlier, the package would put the stock wallpaper back.
#
#   cosmic-set-branding.sh           # the running build root
#   cosmic-set-branding.sh <root>    # write under <root> instead (tests)

set -euo pipefail

root="${1:-}"
WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
conf="${root}/usr/share/cosmic/com.system76.CosmicBackground/v1/all"

if [[ -z "$root" && ! -e "$WALLPAPER" ]]; then
	echo "ERROR: ${WALLPAPER} is missing; system_files should have placed it." >&2
	exit 1
fi

mkdir -p "$(dirname "$conf")"
# filter_by_theme stays false: true lets COSMIC swap in its own dark/light
# pick, which is how the stock wallpaper wins back.
cat >"$conf" <<RON
(
    output: "all",
    source: Path("${WALLPAPER}"),
    filter_by_theme: false,
    rotation_frequency: 300,
    filter_method: Lanczos,
    scaling_mode: Zoom,
    sampling_method: Alphanumeric,
)
RON

echo "COSMIC branding applied: wallpaper=${WALLPAPER}"
