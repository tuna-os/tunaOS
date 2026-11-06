#!/usr/bin/env bash
# Native contract mechanism. The first consumer supports Debian GNOME apt only.
# Call prepare/install before existing trusted hooks, then commit after success.

tunaos_desktop_contract_install() {
	local contract="$1" source="$2" variant="$3" desktop="$4" platform="$5" required
	local yq="${YQ:-yq}"
	_TUNA_DESKTOP_INSTALLED=0
	_TUNA_DESKTOP_CONTRACT_JSON=$(cat "$contract") || return 1
	if ! printf '%s' "$_TUNA_DESKTOP_CONTRACT_JSON" | "$yq" -e '
		.schema_version == 1 and .family == "apt" and .profile == "gnome-debian" and
		(.required | length) > 0 and
		(.required | tag) == "!!seq" and
		(.required | map(select(test("^[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?$") | not)) | length) == 0
	' >/dev/null; then
		echo 'ERROR: invalid or unsupported desktop installation contract' >&2
		return 1
	fi
	_TUNA_DESKTOP_SOURCE="$source"
	_TUNA_DESKTOP_SOURCE_SHA=$(sha256sum "$source" | cut -d ' ' -f1) || return 1
	local key expected actual
	for key in source_sha256 variant desktop platform; do
		case "$key" in
		source_sha256) expected="$_TUNA_DESKTOP_SOURCE_SHA" ;;
		variant) expected="$variant" ;;
		desktop) expected="$desktop" ;;
		platform) expected="$platform" ;;
		esac
		actual=$(printf '%s' "$_TUNA_DESKTOP_CONTRACT_JSON" | "$yq" -r ".${key}") || return 1
		if [[ "$actual" != "$expected" ]]; then
			echo "ERROR: desktop contract ${key} does not match selected source/cell" >&2
			return 1
		fi
	done
	required=$(printf '%s' "$_TUNA_DESKTOP_CONTRACT_JSON" | "$yq" -r '.required[]') || return 1
	local -a packages
	mapfile -t packages <<<"$required"
	pkg_install "${packages[@]}" || return 1
	_TUNA_DESKTOP_INSTALLED=1
}

tunaos_desktop_contract_commit() {
	local destination="$1" temporary current
	[[ "${_TUNA_DESKTOP_INSTALLED:-0}" == 1 && -n "${_TUNA_DESKTOP_CONTRACT_JSON:-}" && -n "${_TUNA_DESKTOP_SOURCE_SHA:-}" ]] || return 1
	current=$(sha256sum "$_TUNA_DESKTOP_SOURCE" | cut -d ' ' -f1) || return 1
	if [[ "$current" != "$_TUNA_DESKTOP_SOURCE_SHA" || -L "$destination" || -L "$(dirname "$destination")" ]]; then
		echo 'ERROR: source changed or unsupported receipt destination' >&2
		return 1
	fi
	mkdir -p "$(dirname "$destination")" || return 1
	temporary=$(mktemp "${destination}.XXXXXX") || return 1
	if ! printf '%s\n' "$_TUNA_DESKTOP_CONTRACT_JSON" >"$temporary" ||
		! chmod 0644 "$temporary" || ! mv -f "$temporary" "$destination"; then
		rm -f "$temporary"
		return 1
	fi
}
