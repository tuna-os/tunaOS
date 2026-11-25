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

fe_niri_line="spawn-at-startup \"sh\" \"-c\" \"${fe_live_guard} && exec flatpak run org.tunaos.InstallerNiri\""
fe_niri_mark='// live medium only: tunaos.live (installer-medium/frontends/niri)'

# fe_niri_append FILE: add the spawn line once. Idempotent on the mark.
fe_niri_append() {
	grep -qxF "${fe_niri_mark}" "$1" && return 0
	printf '\n%s\n%s\n' "${fe_niri_mark}" "${fe_niri_line}" >>"$1"
}

# niri reads ONE config: ~/.config/niri/config.kdl (copied from /etc/skel when
# medium-live-setup creates liveuser), else /etc/niri/config.kdl, else
# /usr/share/niri/config.kdl. Append to every candidate that exists, and seed
# /etc/niri from the /usr default when only that exists, so the line is read
# either way. No config anywhere is fatal: a medium with no launcher looks fine
# and starts nothing (desktop-niri.sh, run 32450214451).
fe_autostart() {
	local etc_cfg="${fe_etc}/niri/config.kdl" skel="${fe_etc}/skel/.config/niri/config.kdl"
	local usr_cfg="${fe_usr:+${fe_usr}/share/niri/config.kdl}" c n=0
	if [[ $1 == plan ]]; then
		fe_say "  niri: append '${fe_niri_line}' to each of ${skel}, ${etc_cfg}, ${usr_cfg:-<no usr>}"
		return 0
	fi
	if [[ ! -f ${etc_cfg} && -n ${usr_cfg} && -f ${usr_cfg} ]]; then
		mkdir -p "$(dirname "${etc_cfg}")"
		cp "${usr_cfg}" "${etc_cfg}"
	fi
	for c in "${skel}" "${etc_cfg}" "${usr_cfg}"; do
		[[ -n ${c} && -f ${c} ]] || continue
		fe_niri_append "${c}"
		n=$((n + 1))
	done
	((n)) || fe_die "no niri config.kdl under ${fe_etc} or ${fe_usr:-<none>}; cannot arrange the autostart"
}

fe_main "$@"
