#!/usr/bin/env bash
# shellcheck disable=SC2154
# Live-session half of a native frontend install (tunaOS#4905).
#
# Sourced by installer-medium/frontends/{kde,cosmic,niri,xfce}/install.sh from
# its fe_autostart, after frontend-common.sh set fe_root, fe_etc, fe_var,
# fe_usr, fe_app, fe_desktop and fe_dry. It writes what install-frontend.sh
# checks and what a live boot needs:
#
#   /etc/xdg/autostart/org.tunaos.installer-live.desktop   runs the launcher
#   /usr/lib/medium-live/live-setup.d/50-DESKTOP-session    the desktop's hook
#   /usr/lib/medium-live/greeter.sh                         the hook's library
#   /usr/share/medium-live/stamp.d/DESKTOP                  "native"
#   /usr/share/medium-live/payload.d/DESKTOP.list           every path above
#
# Nothing here touches a greeter or a compositor config. The image build runs
# in a scratch tree that has neither. The hook writes them at boot, on the RAM
# overlay of a tunaos.live boot (medium-live-setup).
#
# The names start with ls_ because frontend-common.sh and lib.sh both own fe_.

ls_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ls_launcher=/usr/libexec/medium-live-installer
ls_entry=/etc/xdg/autostart/org.tunaos.installer-live.desktop
ls_list=""

# ls_host PATH: where the in-image PATH lives below the staging root.
ls_host() {
	case "$1" in
	/etc/*) printf '%s\n' "${fe_etc}${1#/etc}" ;;
	/var/*) printf '%s\n' "${fe_var}${1#/var}" ;;
	/usr/*) printf '%s\n' "${fe_usr:-${fe_root}/usr}${1#/usr}" ;;
	*) fe_die "live-session: no place for ${1} on the medium" ;;
	esac
}

# ls_record PATH...: add in-image paths to the payload list.
ls_record() {
	printf '%s\n' "$@" >>"${ls_list}"
}

# ls_put MODE PATH: write stdin to the in-image PATH and record it.
ls_put() {
	local dest
	dest="$(ls_host "$2")"
	mkdir -p "$(dirname "${dest}")"
	cat >"${dest}"
	chmod "$1" "${dest}"
	ls_record "$2"
}

# ls_autostart plan|write [--once] [KEY=VALUE...]
# --once makes the launcher refuse a second instance. Use it when the session
# has two start paths (niri: XDG autostart and spawn-at-startup). Each
# KEY=VALUE is one more line of the desktop entry. Never pass OnlyShowIn=:
# systemd-xdg-autostart-generator skips the entry when XDG_CURRENT_DESKTOP
# does not match, and cosmic-session does not export it.
ls_autostart() {
	local mode="$1" once="" hook
	shift
	if [[ ${1:-} == --once ]]; then
		once=" --once"
		shift
	fi
	hook="${ls_dir}/${fe_desktop}/live-setup"
	if [[ ${mode} == plan ]]; then
		fe_say "  xdg autostart ${fe_etc}/xdg/autostart/org.tunaos.installer-live.desktop (${ls_launcher}${once} -- flatpak run ${fe_app})"
		[[ ! -f ${hook} ]] || fe_say "  live boot hook /usr/lib/medium-live/live-setup.d/50-${fe_desktop}-session (greeter autologin)"
		return 0
	fi
	ls_list="$(ls_host "/usr/share/medium-live/payload.d/${fe_desktop}.list")"
	mkdir -p "$(dirname "${ls_list}")"
	: >"${ls_list}"
	{
		printf '[Desktop Entry]\nType=Application\n'
		printf 'Name=Install %s\n' "${TUNAOS_PROJECT_NAME:-TunaOS}"
		printf 'Exec=%s%s -- flatpak run %s\n' "${ls_launcher}" "${once}" "${fe_app}"
		printf 'Icon=%s\n' "${fe_app}"
		if (($#)); then printf '%s\n' "$@"; fi
	} | ls_put 0644 "${ls_entry}"
	if [[ -f ${hook} ]]; then
		ls_put 0644 /usr/lib/medium-live/greeter.sh <"${ls_dir}/live-greeter.sh"
		ls_put 0755 "/usr/lib/medium-live/live-setup.d/50-${fe_desktop}-session" <"${hook}"
	fi
	# The frontend writes $XDG_RUNTIME_DIR/tuna-installer-ready itself.
	printf 'native\n' | ls_put 0644 "/usr/share/medium-live/stamp.d/${fe_desktop}"
	# What fe_main wrote before it called fe_autostart. A directory line
	# stands for the whole tree below it.
	ls_record /etc/tuna-installer/frontend-receipt \
		"/var/lib/flatpak/overrides/${fe_app}" "/var/lib/flatpak/app/${fe_app}"
	sort -u -o "${ls_list}" "${ls_list}"
}
