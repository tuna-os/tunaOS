#!/usr/bin/env bash

# Return the base desktop name for a flavor with one hardware/variant suffix.
tunaos_desktop_flavor() {
	local desktop="$1" suffix
	for suffix in -nvidia-hwe -nvidia -hwe -t2 -cachyos -asahi -x13s -zfs; do
		if [[ "$desktop" == *"$suffix" ]]; then
			desktop="${desktop%"$suffix"}"
			break
		fi
	done
	printf '%s\n' "$desktop"
}
