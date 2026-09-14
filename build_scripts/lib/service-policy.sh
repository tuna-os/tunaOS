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
