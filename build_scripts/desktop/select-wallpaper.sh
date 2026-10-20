#!/usr/bin/env bash
# Pick the most specific wallpaper this image has, for this desktop.
#
#   select-wallpaper.sh <desktop> [root]
#
# Explicit per-desktop artwork wins, then shared anime for the variant. Keep the rendered
# emoji scene as a fallback: the wallpaper renderer only owns <variant>.jpg.
# Copy the winner over tunaos-default.jpg, the path every desktop names.

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

for candidate in "${variant}-${desktop}.jpg" "${variant}-anime.jpg" "${variant}.jpg"; do
	[[ -n "$variant" && -f "${dir}/${candidate}" ]] || continue
	install -m0644 "${dir}/${candidate}" "${dir}/tunaos-default.jpg"
	echo "Wallpaper: ${candidate} (variant=${variant} desktop=${desktop})"
	exit 0
done
echo "Wallpaper: generic tunaos-default.jpg (variant=${variant:-unknown} desktop=${desktop})"
