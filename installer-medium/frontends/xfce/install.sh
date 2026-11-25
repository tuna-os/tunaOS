#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2034,SC2154
# Install the xfce installer frontend on the medium (tunaOS#4905, ADR 0018).
# Usage: install.sh ROOT [--dry-run] | --check-pin
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=frontend-common.sh
. "${HERE}/frontend-common.sh"
fe_desktop=xfce
# BOOTC_INSTALLER_BACKEND=daemon is the switch this frontend reads at the pinned source commit
fe_extra_env=(BOOTC_INSTALLER_BACKEND=daemon)

fe_autostart() {
	if [[ $1 == plan ]]; then
		fe_say "  xdg autostart ${fe_etc}/xdg/autostart/org.tunaos.installer-live.desktop"
	else
		fe_write_xdg_autostart
	fi
}

fe_main "$@"
