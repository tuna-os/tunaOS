#!/usr/bin/env bash
set -euo pipefail

desktop="${1:?usage: verify-desktop-experience.sh <gnome|kde|niri> [--runtime]}"
mode="${2:-build}"

require_command() { command -v "$1" >/dev/null || {
	echo "missing required command: $1" >&2
	exit 1
}; }
require_glob() { compgen -G "$1" >/dev/null || {
	echo "missing required path: $1" >&2
	exit 1
}; }
require_unit() { systemctl list-unit-files "$1.service" --no-legend 2>/dev/null | grep -q "^$1.service" || {
	echo "missing unit: $1.service" >&2
	exit 1
}; }

case "$desktop" in
gnome)
	experience="projectbluefin/bluefin-lts"
	require_command gnome-shell
	require_glob '/usr/share/wayland-sessions/*gnome*.desktop'
	require_unit gdm
	[[ "$mode" == --runtime ]] && dm=gdm
	;;
kde)
	experience="ublue-os/aurora"
	require_command plasmashell
	require_glob '/usr/share/wayland-sessions/*plasma*.desktop'
	require_unit sddm
	[[ "$mode" == --runtime ]] && dm=sddm
	;;
niri)
	experience="zirconium-dev/zirconium"
	require_command niri
	require_glob '/usr/share/wayland-sessions/*niri*.desktop'
	require_unit greetd
	[[ "$mode" == --runtime ]] && dm=greetd
	;;
*) exit 0 ;;
esac

if [[ "$mode" == --runtime ]]; then
	# Each check is individually gated so a single failure doesn't
	# kill the script silently via `set -e`. The final marker is
	# written to the serial console regardless of partial failures.
	ok=1
	if ! command -v remora >/dev/null 2>&1; then
		echo "TUNAOS_DESKTOP_CONTRACT_FAIL reason=remora_not_found" >&2
		ok=0
	fi
	if ! compgen -G '/usr/share/tunaos/experience-contracts/remora' >/dev/null 2>&1; then
		echo "TUNAOS_DESKTOP_CONTRACT_FAIL reason=remora_contract_missing" >&2
		ok=0
	fi
	if ! systemctl is-active --quiet graphical.target 2>/dev/null; then
		echo "TUNAOS_DESKTOP_CONTRACT_FAIL reason=graphical_target_inactive" >&2
		ok=0
	fi
	if ! systemctl is-active --quiet "$dm.service" 2>/dev/null; then
		echo "TUNAOS_DESKTOP_CONTRACT_FAIL reason=dm_inactive dm=$dm" >&2
		ok=0
	fi
	if [[ "$ok" -eq 1 ]]; then
		echo "TUNAOS_DESKTOP_CONTRACT_OK desktop=$desktop experience=$experience" | tee /dev/ttyS0 2>/dev/null || true
	else
		echo "TUNAOS_DESKTOP_CONTRACT_FAIL desktop=$desktop (see journal)" | tee /dev/ttyS0 2>/dev/null || true
	fi
else
	install -d /usr/share/tunaos/experience-contracts
	printf 'desktop=%s\nexperience=%s\nvalidated_at_build=true\n' "$desktop" "$experience" \
		>"/usr/share/tunaos/experience-contracts/${desktop}"
	echo "desktop experience contract passed: $desktop ($experience)"
fi
