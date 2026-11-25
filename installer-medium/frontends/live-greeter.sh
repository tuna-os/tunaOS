#!/usr/bin/bash
# Greeter autologin for the live session (tunaOS#4905).
#
# Installed as /usr/lib/medium-live/greeter.sh and sourced by the hooks in
# /usr/lib/medium-live/live-setup.d. medium-live-setup runs those hooks as
# root, only on a tunaos.live boot, with the live user in $1. The root is a
# RAM overlay then, so nothing written here reaches the medium or an
# installed system.
#
# No function has a default display manager. Each one reads which unit the
# image starts and stops the boot setup when it does not know that unit: a
# guess gives a black screen with no failed unit (AGENTS.md, "A detection
# default is a silent fallback").
#
# MEDIUM_LIVE_ROOT prefixes every path. Only the tests set it.

ml_root="${MEDIUM_LIVE_ROOT:-}"
ml_desktop="${ml_desktop:-?}"
# greetd captures no output of the session command. systemd-cat puts it in the
# journal under this tag (live-iso/common/src/desktop-cosmic.sh has the run).
ml_tag=medium-live-session
# source_profile = false skips /etc/profile, the one place a greetd session
# gets a PATH from (desktop-xfce.sh: the installer found no lsblk).
ml_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin

ml_say() { echo "medium-live[${ml_desktop}]: $*"; }
ml_die() {
	echo "medium-live[${ml_desktop}]: error: $*" >&2
	exit 1
}

# ml_have BIN: the image has the program.
ml_have() {
	local d
	for d in /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin; do
		[[ -x "${ml_root}${d}/$1" ]] && return 0
	done
	return 1
}

# ml_dm_unit: print the display manager unit the image starts. The alias
# display-manager.service names it. Without the alias, exactly one known
# display manager in graphical.target.wants names it. Anything else fails.
ml_dm_unit() {
	local etc="${ml_root}/etc/systemd/system" target u
	local -a hits=()
	if [[ -L "${etc}/display-manager.service" ]]; then
		target="$(readlink "${etc}/display-manager.service")"
		[[ ${target} != /dev/null ]] || ml_die "display-manager.service is masked"
		basename "${target}"
		return 0
	fi
	for u in greetd cosmic-greeter lightdm gdm gdm3 sddm plasmalogin; do
		if [[ -e "${etc}/graphical.target.wants/${u}.service" || -L "${etc}/graphical.target.wants/${u}.service" ]]; then
			hits+=("${u}.service")
		fi
	done
	((${#hits[@]} == 1)) ||
		ml_die "cannot tell which display manager starts: no display-manager.service alias, and graphical.target wants '${hits[*]:-none}'"
	printf '%s\n' "${hits[0]}"
}

# ml_dm_rivals UNIT: warn when graphical.target also wants another display
# manager. bonito:xfce has the alias on lightdm.service and gdm.service in
# graphical.target.wants (image c94c945d8b4c). Both start then; the hook
# configures the one that the alias names and says so in the log.
ml_dm_rivals() {
	local etc="${ml_root}/etc/systemd/system" u
	for u in greetd cosmic-greeter lightdm gdm gdm3 sddm plasmalogin; do
		[[ ${u}.service != "$1" ]] || continue
		if [[ -e "${etc}/graphical.target.wants/${u}.service" || -L "${etc}/graphical.target.wants/${u}.service" ]]; then
			echo "medium-live[${ml_desktop}]: WARNING: graphical.target also wants ${u}.service; the alias names $1" >&2
		fi
	done
}

# ml_unit_file UNIT: print the path of the unit file.
ml_unit_file() {
	local d
	for d in /etc/systemd/system /usr/lib/systemd/system /lib/systemd/system; do
		if [[ -f "${ml_root}${d}/$1" && ! -L "${ml_root}${d}/$1" ]]; then
			printf '%s\n' "${ml_root}${d}/$1"
			return 0
		fi
	done
	ml_die "no unit file for $1"
}

# ml_greetd_config UNIT: print the config file the unit gives to greetd.
# cosmic-greeter.service is greetd with its own file:
#   ExecStart=greetd --config /etc/greetd/cosmic-greeter.toml
# so a write to /etc/greetd/config.toml changes nothing there.
ml_greetd_config() {
	local file line cfg
	file="$(ml_unit_file "$1")"
	line="$(grep -m1 -E '^ExecStart=.*greetd' "${file}")" ||
		ml_die "$1 does not start greetd (${file})"
	cfg="$(sed -n -E 's/.*[[:space:]](--config|-c)[=[:space:]]+([^[:space:]]+).*/\2/p' <<<"${line}")"
	printf '%s\n' "${cfg:-/etc/greetd/config.toml}"
}

# ml_greetd_pam: greetd opens the session through PAM. A base that ships no
# PAM service for it gets a permissive one (desktop-cosmic.sh).
ml_greetd_pam() {
	local svc
	for svc in greetd greetd-greeter; do
		[[ -e "${ml_root}/etc/pam.d/${svc}" || -e "${ml_root}/usr/lib/pam.d/${svc}" ]] && continue
		install -d "${ml_root}/etc/pam.d"
		cat >"${ml_root}/etc/pam.d/${svc}" <<'PAMEOF'
auth     required  pam_permit.so
account  required  pam_permit.so
password required  pam_deny.so
session  required  pam_unix.so
session  optional  pam_systemd.so
PAMEOF
		ml_say "wrote /etc/pam.d/${svc} (the image has none)"
	done
}

# ml_greetd_autologin USER COMMAND...: make greetd start COMMAND as USER.
# The whole file is replaced. The image's file can already hold [general]
# (cosmic-greeter.toml and the dms-greeter config do), and a second table of
# the same name is not valid TOML. initial_session logs in at boot;
# default_session runs the same command when the session ends, because the
# greeter needs a password that the live user does not have.
ml_greetd_autologin() {
	local user="$1" unit cfg command
	shift
	unit="$(ml_dm_unit)"
	case "${unit}" in
	greetd.service | cosmic-greeter.service) ;;
	*) ml_die "the display manager is ${unit}, not greetd; this desktop has no autologin rule for it" ;;
	esac
	ml_dm_rivals "${unit}"
	cfg="$(ml_greetd_config "${unit}")"
	command="systemd-cat -t ${ml_tag} env PATH=${ml_path} $*"
	[[ ${command} != *[\"\\]* ]] || ml_die "session command must hold no quote or backslash: ${command}"
	install -d "$(dirname "${ml_root}${cfg}")"
	cat >"${ml_root}${cfg}" <<GREETDEOF
[terminal]
vt = 1

[general]
source_profile = false

[initial_session]
user = "${user}"
command = "${command}"

[default_session]
user = "${user}"
command = "${command}"
GREETDEOF
	chmod 0644 "${ml_root}${cfg}"
	ml_greetd_pam
	ml_say "greetd autologin: ${unit} reads ${cfg}; ${user} runs '$*'"
}

# ml_lightdm_autologin USER SESSION: make LightDM log USER in to SESSION.
ml_lightdm_autologin() {
	local user="$1" session="$2" unit
	unit="$(ml_dm_unit)"
	[[ ${unit} == lightdm.service ]] ||
		ml_die "the display manager is ${unit}, not LightDM"
	ml_dm_rivals "${unit}"
	install -d "${ml_root}/etc/lightdm/lightdm.conf.d"
	printf '[Seat:*]\nautologin-user=%s\nautologin-user-timeout=0\nautologin-session=%s\n' \
		"${user}" "${session}" >"${ml_root}/etc/lightdm/lightdm.conf.d/90-medium-live-autologin.conf"
	# Some bases let only this group log in with no password (pam_succeed_if
	# in lightdm-autologin).
	groupadd -f autologin
	usermod -aG autologin "${user}"
	ml_say "LightDM autologin: ${user} starts session ${session}"
}
