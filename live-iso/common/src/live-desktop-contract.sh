#!/usr/bin/env bash
# Pure desktop-selection contract for the TunaOS live ISO customization path.

detect_live_desktop() {
	local session_root="${1:-}"

	if [[ -f "${session_root}/usr/share/wayland-sessions/plasma.desktop" ||
		-f "${session_root}/usr/share/wayland-sessions/plasmawayland.desktop" ]]; then
		printf '%s\n' kde
	elif [[ -f "${session_root}/usr/share/wayland-sessions/niri.desktop" ]]; then
		printf '%s\n' niri
	elif [[ -f "${session_root}/usr/share/wayland-sessions/cosmic.desktop" ]]; then
		printf '%s\n' cosmic
	elif compgen -G "${session_root}/usr/share/xsessions/xfce*.desktop" >/dev/null ||
		compgen -G "${session_root}/usr/share/wayland-sessions/xfce*.desktop" >/dev/null; then
		printf '%s\n' xfce
	elif [[ -f "${session_root}/usr/share/wayland-sessions/pantheon-wayland.desktop" ||
		-f "${session_root}/usr/share/xsessions/pantheon.desktop" ]]; then
		printf '%s\n' pantheon
	else
		printf '%s\n' gnome
	fi
}

installer_app_for_desktop() {
	case "${1:?desktop is required}" in
	kde) printf '%s\n' org.tunaos.InstallerKde ;;
	niri) printf '%s\n' org.tunaos.InstallerNiri ;;
	cosmic) printf '%s\n' org.tunaos.InstallerCosmic ;;
	xfce) printf '%s\n' org.tunaos.InstallerXfce ;;
	gnome | pantheon) printf '%s\n' org.bootcinstaller.Installer ;;
	*)
		printf 'unsupported live desktop: %s\n' "$1" >&2
		return 2
		;;
	esac
}
