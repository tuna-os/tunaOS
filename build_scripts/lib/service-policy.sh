#!/usr/bin/env bash

# Service and display-manager policy shared by image build stages.
# This module is sourced by build_scripts/lib.sh; keep it free of source-time
# side effects so the compatibility facade remains safe for every consumer.

# systemctl enable wrapper that tolerates the unit-not-present case.
# Build scripts run in a multi-stage container build where some units may
# only exist on certain variants (e.g. tailscaled on EL10 but not on EL9).
safe_enable() {
	if systemctl list-unit-files "$1" &>/dev/null || [[ -f "/usr/lib/systemd/system/$1" ]]; then
		systemctl enable "$1" || true
	fi
}

# Mirror of safe_enable for disabling. Missing variant-specific units are a
# supported condition, and enabling or disabling an existing unit is idempotent.
safe_disable() {
	if systemctl list-unit-files "$1" &>/dev/null || [[ -f "/usr/lib/systemd/system/$1" ]]; then
		systemctl disable "$1" || true
	fi
}

# Return the KDE display-manager unit installed on the current image.
# Plasma 6.6 renamed SDDM to PlasmaLogin, while Fedora, Debian, Ubuntu and Arch
# still ship sddm.service. _KDE_DM_ROOT lets tests provide an isolated unit tree.
kde_dm_unit() {
	if [[ -e "${_KDE_DM_ROOT:-}/usr/lib/systemd/system/plasmalogin.service" ]] ||
		{ [[ -z "${_KDE_DM_ROOT:-}" ]] &&
			systemctl list-unit-files plasmalogin.service --no-legend 2>/dev/null |
			grep -q '^plasmalogin.service'; }; then
		echo plasmalogin.service
	else
		echo sddm.service
	fi
}

# Guard ublue login banners against non-interactive login shells. greetd and
# `ssh host command` both source profile.d without a terminal, where a banner
# can stall the session before its real command starts. TUNAOS_PROFILE_DIR lets
# contract tests exercise the filesystem mutation without touching /etc.
tunaos_guard_login_banners() {
	local profile_dir="${TUNAOS_PROFILE_DIR:-/etc/profile.d}"
	local banner found=0

	for banner in "${profile_dir}/umotd.sh" "${profile_dir}/uwelcome.sh"; do
		[[ -f "$banner" ]] || continue
		found=$((found + 1))
		if grep -q 'TUNAOS_INTERACTIVE_GUARD' "$banner"; then continue; fi
		{
			if head -n1 "$banner" | grep -q '^#!'; then head -n1 "$banner"; fi
			cat <<'GUARD_EOF'
# TUNAOS_INTERACTIVE_GUARD — added by build_scripts/lib/service-policy.sh.
# A login banner is for interactive logins. Unguarded, this file also runs in
# non-interactive login shells — greetd sessions, `ssh host command` — where
# nothing drains its output and a stall takes the whole session with it.
case $- in
*i*) ;;
*) return 0 ;;
esac
GUARD_EOF
			if head -n1 "$banner" | grep -q '^#!'; then tail -n +2 "$banner"; else cat "$banner"; fi
		} >"${banner}.tunaos-guard"
		# Copy through the original inode so mode and ownership are kept.
		cat "${banner}.tunaos-guard" >"$banner"
		rm -f "${banner}.tunaos-guard"
		echo "guarded ${banner} against non-interactive execution"
	done

	if [[ "$found" -eq 0 ]]; then
		echo "NOTE: no ublue login-banner script found in ${profile_dir} to guard."
		echo "      If upstream renamed it again, update tunaos_guard_login_banners in"
		echo "      build_scripts/lib/service-policy.sh."
	fi
}

# Grant the administrator group `wheel` password-required sudo, and prove at
# build time that the running sudo configuration actually reads the grant.
# GDM/gnome-initial-setup create the first admin with `useradd -G wheel`; Arch
# and Gentoo ship `%wheel` commented out, so that admin got "user NOT in
# sudoers" (tuna-desktop#989). Validation is `visudo -c -f <main sudoers>`
# rather than bare `visudo -c`: openSUSE installs /usr/etc/sudoers at 0444,
# which bare `visudo -c` rejects for its mode, not its content. The drop-in's
# own owner and mode are enforced with -O -P instead. TUNAOS_SUDOERS_ROOT lets
# contract tests run this against a scratch tree.
tunaos_grant_wheel_sudo() {
	local root="${TUNAOS_SUDOERS_ROOT:-}"
	local dir="${root}/etc/sudoers.d"
	# No '.' and no trailing '~': sudo's @includedir skips such names silently.
	local dropin="${dir}/10-tunaos-wheel"
	local main="" candidate tmp report

	if ! command -v visudo >/dev/null 2>&1; then
		echo "ERROR: no visudo in this image; the base Containerfile must install sudo before 40-services.sh grants %wheel." >&2
		return 1
	fi
	for candidate in "${root}/etc/sudoers" "${root}/usr/etc/sudoers"; do
		if [[ -f "$candidate" ]]; then
			main="$candidate"
			break
		fi
	done
	if [[ -z "$main" ]]; then
		echo "ERROR: no sudoers file at ${root}/etc/sudoers or ${root}/usr/etc/sudoers to carry the %wheel grant." >&2
		return 1
	fi

	[[ -d "$dir" ]] || install -d -m 0750 "$dir"
	# Written under a dotted name, which sudo ignores, so a half-written or
	# invalid grant is never live; it moves into place only after visudo agrees.
	tmp="$(mktemp "${dir}/.tunaos-wheel.XXXXXX")"
	printf '%%wheel ALL=(ALL:ALL) ALL\n' >"$tmp"
	if ! visudo -c -f "$tmp"; then
		rm -f "$tmp"
		echo "ERROR: the %wheel sudoers grant failed visudo." >&2
		return 1
	fi
	chmod 0440 "$tmp"
	if [[ "${EUID}" -eq 0 ]]; then
		chown root:root "$tmp"
	fi
	mv -f "$tmp" "$dropin"

	local strict=()
	if [[ "${EUID}" -eq 0 ]]; then strict=(-O -P); fi
	if ! visudo -c "${strict[@]}" -f "$dropin"; then
		echo "ERROR: ${dropin} failed visudo's owner/mode/syntax check." >&2
		return 1
	fi
	if ! report="$(visudo -c -f "$main" 2>&1)"; then
		echo "$report" >&2
		echo "ERROR: ${main} and its includes fail visudo with the %wheel grant in place." >&2
		return 1
	fi
	echo "$report"
	if ! grep -qxF "${dropin}: parsed OK" <<<"$report"; then
		echo "ERROR: ${main} does not include ${dropin}; %wheel would still have no sudo." >&2
		return 1
	fi
	echo "granted %wheel password-required sudo via ${dropin}"
}
