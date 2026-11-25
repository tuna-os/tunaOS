#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2034,SC2154
# Install the kde installer frontend on the medium (tunaOS#4905, ADR 0018).
# Usage: install.sh ROOT [--dry-run] | --check-pin
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=frontend-common.sh
. "${HERE}/frontend-common.sh"
fe_desktop=kde
# kde reads TUNA_INSTALLER_BACKEND, which the library already sets
fe_extra_env=()

fe_autostart() {
	if [[ $1 == plan ]]; then
		fe_say "  xdg autostart ${fe_etc}/xdg/autostart/org.tunaos.installer-live.desktop"
	else
		fe_write_xdg_autostart X-KDE-autostart-phase=2
	fi
}

fe_main "$@"
