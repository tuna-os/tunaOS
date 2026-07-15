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
	require_command remora
	require_glob '/usr/share/tunaos/experience-contracts/remora'
	systemctl is-active --quiet graphical.target
	systemctl is-active --quiet "$dm.service"
	echo "TUNAOS_DESKTOP_CONTRACT_OK desktop=$desktop experience=$experience" | tee /dev/ttyS0 2>/dev/null || true
else
	install -d /usr/share/tunaos/experience-contracts
	printf 'desktop=%s\nexperience=%s\nvalidated_at_build=true\n' "$desktop" "$experience" \
		>"/usr/share/tunaos/experience-contracts/${desktop}"
	echo "desktop experience contract passed: $desktop ($experience)"
fi
