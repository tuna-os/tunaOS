#!/usr/bin/env bash
# Point COSMIC at the variant's wallpaper instead of the stock nebula.
#
# cosmic-bg reads its system default from
# /usr/share/cosmic/<config id>/v1/all, and the cosmic-bg package ships those
# files naming /usr/share/backgrounds/cosmic/*. So this runs after the desktop
# install (both call sites, like gnome-set-branding.sh); written any earlier,
# the package would put the stock wallpaper back.
#
# Three config ids, because cosmic-bg changed its layout (pop-os/cosmic-bg
# d6dcfa9, 2026-11-06, "add per-mode backgrounds"). Newer releases read
# com.system76.CosmicBackground.Dark or .Light for the current theme mode, and
# copy only the user's own old config into them, never the system default.
# Without a system default for the mode, cosmic-bg falls back to
# Entry::fallback(), system76-cosmic-dark.png (config/src/lib.rs). Older
# releases read com.system76.CosmicBackground. Write all three.
#
#   cosmic-set-branding.sh           # the running build root
#   cosmic-set-branding.sh <root>    # write under <root> instead (tests)

set -euo pipefail

root="${1:-}"
WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg

if [[ -z "$root" && ! -e "$WALLPAPER" ]]; then
	echo "ERROR: ${WALLPAPER} is missing; system_files should have placed it." >&2
	exit 1
fi

for id in com.system76.CosmicBackground com.system76.CosmicBackground.Dark com.system76.CosmicBackground.Light; do
	dir="${root}/usr/share/cosmic/${id}/v1"
	mkdir -p "$dir"
	# A per-output entry from a package would beat "all" on that output.
	rm -f "${dir}"/output.*
	# filter_by_theme stays false: true lets COSMIC swap in its own dark/light
	# pick, which is how the stock wallpaper wins back.
	cat >"${dir}/all" <<RON
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
done

echo "COSMIC branding applied: wallpaper=${WALLPAPER}"
