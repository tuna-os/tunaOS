#!/usr/bin/env bash

# Return the desktop a flavor installs, read from the exact per-flavor
# [flavor_metadata.<id>] desktop in tunaos.toml (generated into
# docs/iso-builder.flavors.json by `scripts/config.py generate-builder-flavors`).
# Headless flavors (desktop = "none") answer "base", which callers skip.
# An unconfigured flavor is an error, not a guess from its suffix.
TUNAOS_FLAVOR_METADATA="${TUNAOS_FLAVOR_METADATA:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/docs/iso-builder.flavors.json}"

tunaos_desktop_flavor() {
	local desktop
	desktop="$(jq -er --arg id "$1" '.flavors[] | select(.id == $id) | .desktop' "$TUNAOS_FLAVOR_METADATA")" || {
		echo "tunaos_desktop_flavor: flavor '$1' has no [flavor_metadata] entry in $TUNAOS_FLAVOR_METADATA" >&2
		return 1
	}
	[[ "$desktop" == none ]] && desktop=base
	printf '%s\n' "$desktop"
}
