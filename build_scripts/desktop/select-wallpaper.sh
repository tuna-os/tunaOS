#!/usr/bin/env bash
# Pick the most specific wallpaper this image has, for this desktop.
#
#   select-wallpaper.sh <desktop> [root]
#
# Artwork is per variant AND per desktop where someone has painted one
# (wahoo-gnome.jpg: the koinobori scene in GNOME's calm style), else per
# variant (wahoo.jpg, the rendered emoji scene, which 90-image-info.sh already
# installed), else the generic TunaOS scene. The winner is copied over
# tunaos-default.jpg, the one path every desktop's config names, so no desktop
# needs to know about variants. Runs from both desktop call sites, before the
# per-desktop branding.

set -euo pipefail

desktop="${1:?usage: select-wallpaper.sh <desktop> [root]}"
root="${2:-}"
dir="${root}/usr/share/backgrounds/tunaos"
identity="${root}/usr/share/tunaos/identity.env"

variant=""
if [[ -f "$identity" ]]; then
	variant="$(sed -n 's/^TUNAOS_VARIANT=//p' "$identity" | tr -d "'\"")"
fi
# gnome-nvidia, kde-cachyos, ... are the same desktop.
desktop="${desktop%%-*}"

for candidate in "${variant}-${desktop}.jpg" "${variant}.jpg"; do
	[[ -n "$variant" && -f "${dir}/${candidate}" ]] || continue
	install -m0644 "${dir}/${candidate}" "${dir}/tunaos-default.jpg"
	echo "Wallpaper: ${candidate} (variant=${variant} desktop=${desktop})"
	exit 0
done
echo "Wallpaper: generic tunaos-default.jpg (variant=${variant:-unknown} desktop=${desktop})"
