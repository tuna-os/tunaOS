#!/usr/bin/env bash
# Tuna images offer exactly one login session. GDM falls back to its own
# default (currently the GNOME session, which is broken on newer GNOME and
# ignores per-user/default selection on some bases), so hide every other
# Wayland session entry instead of relying on the chooser default.
set -euo pipefail

_TD_ROOT="${TUNAOS_GDM_SESSIONS_ROOT:-}"
_TD_DIR="${_TD_ROOT}/usr/share/wayland-sessions"
changed=0
for desktop in "$_TD_DIR"/*.desktop; do
	[ -e "$desktop" ] || continue
	case "$(basename "$desktop")" in
	tuna*.desktop | roost.desktop) continue ;;
	esac
	if ! grep -qx 'NoDisplay=true' "$desktop"; then
		printf '\nNoDisplay=true\n' >>"$desktop"
		changed=1
	fi
done
echo "hid non-Tuna sessions: changed=${changed}"
