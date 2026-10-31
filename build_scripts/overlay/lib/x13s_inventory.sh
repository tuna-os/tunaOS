#!/usr/bin/env bash

inventory_file() {
	local expected="$1" dir base candidate
	local -a matches=()
	dir="${expected%/*}"
	base="${expected##*/}"
	for candidate in "$dir/$base" "$dir/$base.xz" "$dir/$base.zst"; do
		[[ -f "$candidate" ]] && matches+=("$candidate")
	done
	if ((${#matches[@]})); then
		mapfile -t matches < <(printf '%s\n' "${matches[@]}" | LC_ALL=C sort)
		printf 'PRESENT %s -> %s\n' "$expected" "${matches[*]}"
	else
		printf 'MISSING %s\n' "$expected"
	fi
}
