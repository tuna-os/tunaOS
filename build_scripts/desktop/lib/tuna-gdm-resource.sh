#!/usr/bin/env bash

# Rebuild a GNOME Shell theme GResource in a disposable workspace. The target is
# replaced only after extraction and compilation succeed, so a compiler failure
# leaves the distro resource untouched.
tuna_gdm_rebuild_resource() {
	local resource="$1" theme="$2" tmp xml output list name relative path
	local css_count=0
	local -a resources=()

	[[ -f "$resource" ]] || { echo "tuna-gdm: resource is missing: $resource" >&2; return 1; }
	[[ -f "$theme" ]] || { echo "tuna-gdm: theme source is missing: $theme" >&2; return 1; }
	tmp="$(mktemp -d)" || return 1
	xml="$tmp/theme.gresource.xml"
	output="$tmp/gnome-shell-theme.gresource"
	if ! list="$(gresource list "$resource")"; then
		rm -rf "$tmp"
		return 1
	fi
	mapfile -t resources <<<"$list"
	if ((${#resources[@]} == 0)); then
		echo "tuna-gdm: GDM theme resource is empty" >&2
		rm -rf "$tmp"
		return 1
	fi

	{
		printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>'
		printf '%s\n' '<gresources>'
		printf '%s\n' '  <gresource prefix="/org/gnome/shell/theme">'
		for name in "${resources[@]}"; do
			[[ -n "$name" ]] || continue
			relative="${name#/org/gnome/shell/theme/}"
			[[ "$relative" != "$name" ]] || continue
			path="$tmp/$relative"
			mkdir -p "$(dirname "$path")"
			if ! gresource extract "$resource" "$name" >"$path"; then
				rm -rf "$tmp"
				return 1
			fi
			case "$relative" in
			gnome-shell*.css|*/gnome-shell*.css)
				printf '\n' >>"$path"
				if ! cat "$theme" >>"$path"; then
					rm -rf "$tmp"
					return 1
				fi
				css_count=$((css_count + 1))
				;;
			esac
			printf '    <file>%s</file>\n' "$relative"
		done
		printf '%s\n' '  </gresource>'
		printf '%s\n' '</gresources>'
	} >"$xml"

	((css_count > 0)) || {
		echo "tuna-gdm: GDM theme resource has no stylesheet" >&2
		rm -rf "$tmp"
		return 1
	}
	if ! glib-compile-resources "$xml" --sourcedir="$tmp" --target="$output"; then
		rm -rf "$tmp"
		return 1
	fi
	if ! install -m0644 "$output" "$resource"; then
		rm -rf "$tmp"
		return 1
	fi
	rm -rf "$tmp"
	printf '%d\n' "$css_count"
}
