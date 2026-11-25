#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2034,SC2154
# Install the niri installer frontend on the medium (tunaOS#4905, ADR 0018).
# Usage: install.sh ROOT [--dry-run] | --check-pin
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=frontend-common.sh
. "${HERE}/frontend-common.sh"
fe_desktop=niri
fe_extra_env=()

# The live-session files (autostart entry, boot hook, payload list) come from
# ../live-session.sh. It is read here, not at the top: --check-pin needs only
# the pin.
# niri gets a second start path at boot (niri/live-setup), so the launcher
# runs with --once.
fe_autostart() {
	# shellcheck source=../live-session.sh disable=SC1091
	. "${MEDIUM_FRONTENDS:-${HERE}/..}/live-session.sh"
	ls_autostart "$1" --once
}

fe_main "$@"
