#!/usr/bin/env bash
# Pure flavor metadata helpers. This library intentionally has no source-time
# side effects so recipe generators and tests can consume the flavor contract
# without importing podman, tacklebox, or boot-backend infrastructure.

# Render a flavor id (for example, gnome-nvidia-hwe) as a boot-menu title.
tunaos_flavor_title() {
	local flavor="${1:?flavor required}"
	local base="$flavor" mods=() suffix=""

	if [[ "$base" == *-nvidia-hwe ]]; then
		mods=("NVIDIA" "HWE")
		base="${base%-nvidia-hwe}"
	elif [[ "$base" == *-nvidia ]]; then
		mods=("NVIDIA")
		base="${base%-nvidia}"
	elif [[ "$base" == *-hwe ]]; then
		mods=("HWE")
		base="${base%-hwe}"
	fi

	local name
	case "$base" in
	gnome) name="GNOME" ;;
	kde) name="KDE Plasma" ;;
	cosmic) name="COSMIC" ;;
	niri) name="Niri" ;;
	base) name="Base" ;;
	*) name="${base^}" ;;
	esac

	if ((${#mods[@]})); then
		local joined="${mods[0]}" i
		for ((i = 1; i < ${#mods[@]}; i++)); do
			joined+=", ${mods[i]}"
		done
		suffix=" (${joined})"
	fi
	printf '%s%s\n' "$name" "$suffix"
}

# Map a flavor id to the desktop session used by tacklebox livesys helpers.
tunaos_flavor_desktop() {
	local flavor="${1:?flavor required}"
	case "$flavor" in
	kde*) echo "kde" ;;
	niri*) echo "niri" ;;
	cosmic*) echo "cosmic" ;;
	xfce*) echo "xfce" ;;
	gnome* | *) echo "gnome" ;;
	esac
}
