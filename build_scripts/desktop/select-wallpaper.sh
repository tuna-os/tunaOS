#!/usr/bin/env bash
# Pick the wallpaper this image has, for this desktop.
#
#   select-wallpaper.sh <desktop> [root]
#
# Explicit per-desktop artwork wins, then the variant's anime wallpaper
# <variant>.jpg. Copy the winner over tunaos-default.jpg, the path every
# desktop names. A known variant without a wallpaper is a build error.

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

# RPM and Gentoo set up the desktop before 90-image-info.sh writes the
# identity. Keep the shipped generic wallpaper; 90-image-info.sh runs this
# selector again when the variant is known.
if [[ -z "$variant" ]]; then
	if [[ ! -f "${dir}/tunaos-default.jpg" ]]; then
		echo "ERROR: no variant identity and no ${dir}/tunaos-default.jpg" >&2
		exit 1
	fi
	echo "Wallpaper: generic tunaos-default.jpg (variant unknown, desktop=${desktop})"
	exit 0
fi

for candidate in "${variant}-${desktop}.jpg" "${variant}.jpg"; do
	[[ -f "${dir}/${candidate}" ]] || continue
	install -m0644 "${dir}/${candidate}" "${dir}/tunaos-default.jpg"
	echo "Wallpaper: ${candidate} (variant=${variant} desktop=${desktop})"
	exit 0
done
echo "ERROR: variant ${variant} has no wallpaper: add ${dir}/${variant}.jpg" >&2
exit 1
