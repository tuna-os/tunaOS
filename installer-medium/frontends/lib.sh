#!/usr/bin/env bash
# Helpers for per-desktop frontend installers (tunaOS#4905).
#
# Source this from installer-medium/frontends/<desktop>/install.sh:
#
#   source "${MEDIUM_FRONTENDS:?run through install-frontend.sh}/lib.sh"
#   fe_init "$1" kde
#
# Every function writes below the ROOT that fe_init got and records each path
# it creates in ROOT/usr/share/medium-live/payload.d/<desktop>.list. The
# install post hook reads those lists to remove the frontend from the
# installed copy. See frontends/README.md for the full contract.

FE_ROOT=""
FE_DESKTOP=""
FE_LIST=""
FE_LAUNCHER="/usr/libexec/medium-live-installer"
FE_AUTOSTART="/etc/xdg/autostart/org.tunaos.installer-live.desktop"

fe_die() {
	echo "install-frontend: ${FE_DESKTOP:-?}: $*" >&2
	exit 1
}

# fe_init ROOT DESKTOP: bind the staging root and start a fresh payload list.
fe_init() {
	FE_ROOT="${1:?fe_init ROOT DESKTOP}"
	FE_DESKTOP="${2:?fe_init ROOT DESKTOP}"
	[[ "${FE_ROOT}" == /* && "${FE_ROOT}" != / ]] || fe_die "ROOT must be an absolute path other than /, got '${FE_ROOT}'"
	[[ -d "${FE_ROOT}" ]] || fe_die "ROOT ${FE_ROOT} is not a directory"
	FE_LIST="${FE_ROOT}/usr/share/medium-live/payload.d/${FE_DESKTOP}.list"
	install -d "$(dirname "${FE_LIST}")"
	: >"${FE_LIST}"
}

# fe_record PATH...: add absolute in-image paths to the payload list.
fe_record() {
	[[ -n "${FE_LIST}" ]] || fe_die "fe_init has not run"
	local p
	for p in "$@"; do
		[[ "${p}" == /* ]] || fe_die "payload path must be absolute: ${p}"
		printf '%s\n' "${p}" >>"${FE_LIST}"
	done
}

# fe_install MODE SRC DEST: install one file at DEST (absolute, in-image).
fe_install() {
	local mode="$1" src="$2" dest="$3"
	[[ -f "${src}" ]] || fe_die "missing source file ${src}"
	install -D -m "${mode}" "${src}" "${FE_ROOT}${dest}"
	fe_record "${dest}"
}

# fe_write MODE DEST: write stdin to DEST.
fe_write() {
	local mode="$1" dest="$2"
	install -d "$(dirname "${FE_ROOT}${dest}")"
	cat >"${FE_ROOT}${dest}"
	chmod "${mode}" "${FE_ROOT}${dest}"
	fe_record "${dest}"
}

# fe_install_tree SRCDIR: copy a destdir tree (usr/..., etc/...) over ROOT and
# record each file it adds. Symlinks stay links.
fe_install_tree() {
	local src="$1" f rel
	[[ -d "${src}" ]] || fe_die "missing source tree ${src}"
	cp -a "${src}/." "${FE_ROOT}/"
	while IFS= read -r f; do
		rel="${f#"${src}"}"
		fe_record "${rel}"
	done < <(find "${src}" \( -type f -o -type l \) | sort)
}

# fe_autostart NAME [--stamp APP_ID:WINDOW:SIGNAL] [--bus-name NAME] -- COMMAND...
# Write the live session's autostart entry. The entry runs the launcher,
# which does nothing outside a tunaos.live boot, sets
# TUNA_INSTALLER_BACKEND=daemon and, with --stamp, writes the readiness
# stamp once --bus-name appears on the session bus. Deliberately no
# OnlyShowIn=: systemd-xdg-autostart-generator gates on XDG_CURRENT_DESKTOP
# and a mismatch skips the unit without a word (desktop-cosmic.sh, #4459).
fe_autostart() {
	local name="$1" icon="" launcher_args=() cmd=()
	shift
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--icon)
			icon="$2"
			shift 2
			;;
		--stamp | --bus-name)
			launcher_args+=("$1" "$2")
			shift 2
			;;
		--)
			shift
			cmd=("$@")
			break
			;;
		*) fe_die "fe_autostart: unknown argument $1" ;;
		esac
	done
	[[ ${#cmd[@]} -gt 0 ]] || fe_die "fe_autostart: no command after --"
	{
		echo "[Desktop Entry]"
		echo "Type=Application"
		echo "Name=${name}"
		echo "Exec=${FE_LAUNCHER} ${launcher_args[*]} -- ${cmd[*]}"
		[[ -z "${icon}" ]] || echo "Icon=${icon}"
		echo "X-GNOME-Autostart-enabled=true"
		echo "NoDisplay=false"
	} | fe_write 0644 "${FE_AUTOSTART}"
}

# fe_stamp native|launcher: declare who writes $XDG_RUNTIME_DIR/tuna-installer-ready.
# native: the frontend writes it (docs/INSTALLER-FRONTENDS.md, section 1).
# launcher: medium-live-installer writes it (--stamp on the autostart entry).
fe_stamp() {
	case "$1" in
	native | launcher) ;;
	*) fe_die "fe_stamp: expected native or launcher, got '$1'" ;;
	esac
	install -d "${FE_ROOT}/usr/share/medium-live/stamp.d"
	printf '%s\n' "$1" >"${FE_ROOT}/usr/share/medium-live/stamp.d/${FE_DESKTOP}"
	fe_record "/usr/share/medium-live/stamp.d/${FE_DESKTOP}"
}

# fe_live_setup_hook NAME: write stdin as /usr/lib/medium-live/live-setup.d/NAME.
# medium-live-setup runs each hook as root on live boots only, with the live
# user as $1. Use it for what only a live boot may change.
fe_live_setup_hook() {
	fe_write 0755 "/usr/lib/medium-live/live-setup.d/$1"
}
