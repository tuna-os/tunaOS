#!/usr/bin/env bash
# Make the variant wallpaper the Pantheon default, in the session and on the
# login screen.
#
# Session: elementary-default-settings ships
# [org.gnome.desktop.background:Pantheon] naming elementaryos-default. A
# per-desktop section beats a plain one whatever the file order, so
# zzzz-tunaos.gschema.override carries a :Pantheon section too. Measured on
# gurnard:pantheon (263de4c818f4) before that section existed:
# `XDG_CURRENT_DESKTOP=Pantheon gsettings get org.gnome.desktop.background
# picture-uri` returned 'file:///usr/share/backgrounds/elementaryos-default'.
# Compile here so the build check reads what the session will.
#
# Greeter: io.elementary.greeter 8.1.2 draws a user card from the account's
# synced wallpaper, else from the fixed path below
# (src/Widgets/BackgroundImage.vala). elementary-wallpapers, which provides
# it, is not installed, so the first-boot card had no wallpaper at all.
#
# Idempotent. verify-desktop-wallpaper.sh asserts the result.
#
#   pantheon-set-branding.sh           # the running build root
#   pantheon-set-branding.sh <root>    # write under <root> instead (tests)

set -euo pipefail

root="${1:-}"
WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg

if [[ -z "$root" && ! -e "$WALLPAPER" ]]; then
	echo "ERROR: ${WALLPAPER} is missing; system_files should have placed it." >&2
	exit 1
fi

mkdir -p "${root}/usr/share/backgrounds"
ln -sfn "$WALLPAPER" "${root}/usr/share/backgrounds/elementaryos-default"
echo "Pantheon greeter fallback: /usr/share/backgrounds/elementaryos-default -> ${WALLPAPER}"

schemas="${root}/usr/share/glib-2.0/schemas"
if [[ -d "$schemas" ]] && command -v glib-compile-schemas >/dev/null 2>&1; then
	glib-compile-schemas "$schemas"
	echo "Pantheon: compiled ${schemas#"${root}"}"
fi
