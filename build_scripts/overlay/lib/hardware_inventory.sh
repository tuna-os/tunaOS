#!/usr/bin/env bash
# hardware_inventory.sh — inventory checks shared by hardware-profile.sh.
# Every function prints one PRESENT/MODULE/BUILTIN line, or a MISSING line
# that fails the build once the report is written.

# A firmware file is present uncompressed or as the .xz/.zst payloads Linux
# firmware loading supports; backup suffixes and dangling links are not.
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

# inventory_kconfig <config file> <CONFIG_SYMBOL> [optional]
inventory_kconfig() {
	local config="$1" symbol="$2" optional="${3:-}" line
	line="$(grep -m1 -E "^${symbol}=(y|m)$" "${config}" || true)"
	if [[ -n "${line}" ]]; then
		echo "${line}"
	elif [[ -n "${optional}" ]]; then
		printf 'OPTIONAL-MISSING %s\n' "${symbol}"
	else
		printf 'MISSING %s\n' "${symbol}"
	fi
}

# inventory_module <module dir> <name>: a loadable module (.ko, .ko.xz or
# .ko.zst, with - and _ interchangeable) or one listed in modules.builtin.
inventory_module() {
	local module_dir="$1" module="$2" pattern path
	pattern="${module//[-_]/[-_]}"
	path="$(find "${module_dir}/kernel" -type f -regextype posix-extended \
		-regex ".*/${pattern}\.ko(\.xz|\.zst)?" -print 2>/dev/null | LC_ALL=C sort | head -n1 || true)"
	if [[ -n "${path}" ]]; then
		printf 'MODULE %s -> %s\n' "${module}" "${path}"
	elif grep -qE "/${pattern}\.ko$" "${module_dir}/modules.builtin" 2>/dev/null; then
		printf 'BUILTIN %s\n' "${module}"
	else
		printf 'MISSING %s\n' "${module}"
	fi
}
