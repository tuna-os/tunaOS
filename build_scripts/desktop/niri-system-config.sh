#!/usr/bin/env bash
# Install the TunaOS niri config where niri reads it (tunaOS#5053).
#
# niri reads ~/.config/niri/config.kdl, else /etc/niri/config.kdl, and never
# /usr/share/niri/config.kdl. The image shipped only the /usr/share copy, so a
# user that the installer made got niri's built-in default config at first
# login: alacritty/fuzzel/swaylock hints on a grey screen, no shell (bonito:niri
# pod run on medium 45828155977, usb-6-desktop-status.png).
#
# On an image with DankMaterialShell (dms and its user unit), DMS is the shell:
# the session-shell lines of the config (swaybg, waybar, nm-applet, swaync) go,
# and dms.service starts with the graphical session for every user. DMS draws
# the bar, tray, notifications and wallpaper (tunaos-dms-wallpaper.service sets
# the variant wallpaper). Two bars and two notification daemons would fight
# over org.freedesktop.Notifications.
#
# Sourced by install-desktop.sh from the niri manifests' post_install list: it
# must never call `exit`. TUNAOS_SYSROOT is for tests.
_nsc_root="${TUNAOS_SYSROOT:-}"
_nsc_src="${_nsc_root}/usr/share/niri/config.kdl"
_nsc_dst="${_nsc_root}/etc/niri/config.kdl"
if [[ -f "${_nsc_src}" ]]; then
	install -D -m 0644 "${_nsc_src}" "${_nsc_dst}"
	if [[ -x "${_nsc_root}/usr/bin/dms" && -f "${_nsc_root}/usr/lib/systemd/user/dms.service" ]]; then
		sed -i '/^\/\/ session-shell begin/,/^\/\/ session-shell end/d' "${_nsc_dst}"
		install -d -m 0755 "${_nsc_root}/etc/systemd/user/graphical-session.target.wants"
		ln -sf /usr/lib/systemd/user/dms.service \
			"${_nsc_root}/etc/systemd/user/graphical-session.target.wants/dms.service"
		echo "niri-system-config: ${_nsc_dst} without the session-shell lines; dms.service on for every user"
	else
		echo "niri-system-config: ${_nsc_dst} from ${_nsc_src}"
	fi
else
	echo "::warning title=niri config missing::${_nsc_src} does not exist; niri users get niri's built-in default" >&2
fi
unset _nsc_root _nsc_src _nsc_dst
