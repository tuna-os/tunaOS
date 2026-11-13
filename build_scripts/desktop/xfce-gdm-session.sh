#!/usr/bin/env bash
# XFCE images that use GDM offer exactly one login session: XFCE.
#
# Arch's gdm package depends on gnome-shell and gnome-session, so the XFCE
# image carries GNOME's session entries even though nobody asked for GNOME.
# GDM's fallback prefers GNOME when a user has no saved session, so an
# autologin or a first password login lands in GNOME Shell: marlin-xfce
# (iso-builder run 43429585359) showed "Marlin Installer" on a GNOME top bar
# and the XFCE driver never reached its second page. GNOME's greeter does not
# read these entries (it runs the gdm session), so deleting them removes the
# fallback without touching the login screen.
#
# TUNAOS_XFCE_GDM_ROOT prefixes the paths for tests/test_xfce_gdm_session.py.
set -euo pipefail

_XG_ROOT="${TUNAOS_XFCE_GDM_ROOT:-}"
_xg_have_xfce=0
for _xg_dir in wayland-sessions xsessions; do
	for _xg_name in xfce xfce4 xfce-wayland; do
		[[ -f "${_XG_ROOT}/usr/share/${_xg_dir}/${_xg_name}.desktop" ]] && _xg_have_xfce=1
	done
done
if [[ "$_xg_have_xfce" != 1 ]]; then
	# Removing GNOME's entries with no XFCE entry left would leave no session.
	echo "ERROR: no XFCE session entry in /usr/share/{xsessions,wayland-sessions}" >&2
	exit 1
fi

_xg_removed=0
for _xg_dir in wayland-sessions xsessions; do
	for _xg_file in "${_XG_ROOT}/usr/share/${_xg_dir}"/*.desktop; do
		[[ -e "$_xg_file" ]] || continue
		case "$(basename "$_xg_file")" in
		xfce*.desktop) ;;
		*)
			rm -f -- "$_xg_file"
			_xg_removed=$((_xg_removed + 1))
			;;
		esac
	done
done
echo "removed non-XFCE session entries: ${_xg_removed}"
