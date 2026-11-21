#!/usr/bin/env bash
# Make the variant wallpaper the XFCE default on every monitor and greeter.
#
# xfdesktop keys its wallpaper on the monitor's connector
# (/backdrop/screen0/monitor<eDP-1>/workspace0/last-image). It has no
# wildcard key. A monitor without that key draws DEFAULT_BACKDROP, a path
# compiled into the binary (xfdesktop src/xfdesktop-backdrop-renderer.c:653).
# Each distro picks its own path at build time. Measured in the binaries:
#
#   upstream, EL10, Arch, Debian 13  /usr/share/backgrounds/xfce/xfce-x.svg
#   Fedora                           /usr/share/backgrounds/images/default.jxl
#   Debian sid                       /usr/share/images/desktop-base/default
#   Ubuntu 26.04                     /usr/share/xfce4/backdrops/xubuntu-wallpaper.png
#
# So the default lives at that path. Read it out of the binary, and make it a
# link to the variant wallpaper. Then the first session, every connector and a
# monitor plugged in later all draw the variant. A first-login script used to
# do this per connector, after `sleep 3`; on Wayland it found no monitors and
# left the distro default.
#
# The greeters: LightDM's GTK greeter merges its config files and the last
# `background=` wins. /etc/lightdm/lightdm-gtk-greeter.conf is read last, and
# Fedora's names /usr/share/backgrounds/default.jxl, so our conf.d drop-in
# alone lost. gtkgreet's stylesheet comes from greetd-gtkgreet.sh. Where GDM
# is the display manager (bonito:xfce), give it the variant lettermark the
# way Tuna does: the GDM database only, no GNOME session defaults.
#
# Idempotent. verify-desktop-wallpaper.sh asserts the result.
#
#   xfce-set-branding.sh           # the running build root
#   xfce-set-branding.sh <root>    # write under <root> instead (tests)

set -euo pipefail

root="${1:-}"
WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The checker owns the one reader of DEFAULT_BACKDROP, so both agree on it.
checker="${here}/../checks/verify-desktop-wallpaper.sh"

if [[ -z "$root" && ! -e "$WALLPAPER" ]]; then
	echo "ERROR: ${WALLPAPER} is missing; system_files should have placed it." >&2
	exit 1
fi

backdrop="$("$checker" --xfce-default-backdrop ${root:+--root "$root"})"
mkdir -p "$(dirname "${root}${backdrop}")"
ln -sfn "$WALLPAPER" "${root}${backdrop}"
echo "XFCE default backdrop: ${backdrop} -> ${WALLPAPER}"

# A system or skeleton xfconf file can still name an image for a connector.
for xml in "${root}/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml" \
	"${root}/etc/skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml"; do
	[[ -f "$xml" ]] || continue
	sed -i -E "s#(name=\"(last-image|image-path|last-single-image)\"[^>]*value=\")[^\"]*\"#\\1${WALLPAPER}\"#g" "$xml"
	echo "XFCE xfconf defaults point at ${WALLPAPER}: ${xml#"${root}"}"
done

# Every file the GTK greeter merges, in its order (lightdm-gtk-greeter
# src/greeterconfiguration.c config_init): XDG data dirs, XDG config dirs,
# then /etc. Rewrite each active background= line.
for base in /usr/local/share /usr/share /etc/xdg /etc; do
	for conf in "${root}${base}"/lightdm/lightdm-gtk-greeter.conf.d/*.conf "${root}${base}/lightdm/lightdm-gtk-greeter.conf"; do
		[[ -f "$conf" ]] || continue
		grep -qE '^[[:space:]]*background[[:space:]]*=' "$conf" || continue
		sed -i -E "s#^[[:space:]]*background[[:space:]]*=.*#background=${WALLPAPER}#" "$conf"
		echo "LightDM GTK greeter background: ${conf#"${root}"}"
	done
done

if [[ -f "${root}/usr/lib/systemd/system/gdm.service" || -f "${root}/usr/lib/systemd/system/gdm3.service" ]]; then
	TUNAOS_BRANDING_DESKTOP=tuna "${here}/gnome-set-branding.sh" "$root"
fi
