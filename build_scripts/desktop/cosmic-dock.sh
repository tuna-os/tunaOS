#!/usr/bin/env bash
# cosmic-dock.sh — the COSMIC dock lists only apps this image has.
#
# Sourced by install-desktop.sh via the COSMIC manifests' post_install list.
#
# WHY (tunaOS#2192). COSMIC's upstream default dock pins Files, Firefox,
# Terminal, Text Editor, Store and Settings. Every base ships Files, Terminal
# and Settings, but not all of them package cosmic-edit and cosmic-store
# (Ubuntu's PPA has them for amd64 only), and Firefox arrives later as a
# Flatpak (flatpak-preinstall.sh). So a first boot showed broken icons for
# whatever was missing. Instead of a fixed list that has to match every
# base, write the system default from the desktop files that are actually
# installed. cosmic-config reads /usr/share/cosmic/<component>/v1/<key> as
# the default, and a user's own dock edits still override it.

tunaos_cosmic_dock() {
	local root="${1:-}"
	local -a candidates=(
		com.system76.CosmicFiles
		com.system76.CosmicTerm
		com.system76.CosmicEdit
		com.system76.CosmicStore
		com.system76.CosmicSettings
	)
	local -a pinned=()
	local id
	for id in "${candidates[@]}"; do
		if [[ -f "${root}/usr/share/applications/${id}.desktop" ]]; then
			pinned+=("$id")
		fi
	done
	if ((${#pinned[@]} == 0)); then
		echo "cosmic-dock: no COSMIC apps installed; leaving the dock default alone"
		return 0
	fi

	local dest="${root}/usr/share/cosmic/com.system76.CosmicAppList/v1/favorites"
	mkdir -p "$(dirname "$dest")"
	{
		echo "["
		for id in "${pinned[@]}"; do
			printf '    "%s",\n' "$id"
		done
		echo "]"
	} >"$dest"
	echo "cosmic-dock: pinned ${pinned[*]}"
}

tunaos_cosmic_dock "${TUNAOS_COSMIC_DOCK_ROOT:-}"
