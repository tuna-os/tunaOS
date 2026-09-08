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
