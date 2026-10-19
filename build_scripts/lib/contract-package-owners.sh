#!/usr/bin/env bash
# Loaded only for explicitly requested build-time evidence. No package writes.
contract_owner_evidence_init() {
	local source="$1"
	[[ "${mode:-}" == build && "${desktop:-}" =~ ^(gnome|xfce)$ ]] || {
		echo 'owner evidence supports only GNOME/XFCE build checks' >&2
		return 1
	}
	TUNAOS_OWNER_COLLECTOR="$(dirname -- "${BASH_SOURCE[0]}")/contract-package-owners.py"
	TUNAOS_OWNER_SOURCE="$source"
	python3 "$TUNAOS_OWNER_COLLECTOR" --validate-output \
		--output "$TUNAOS_CONTRACT_OWNER_EVIDENCE" --source "$source" \
		--manager "${TUNAOS_CONTRACT_OWNER_MANAGER:?set apt or dnf for owner evidence}" --desktop "$desktop" || return 1
	TUNAOS_OWNER_EVENTS="$(mktemp)" || return 1
	TUNAOS_OWNER_COMPLETED=0
}

contract_owner_record() {
	[[ -n "${TUNAOS_OWNER_EVENTS:-}" ]] || return 0
	local kind="$1" selector="$2" path
	local -a paths=()
	case "$kind" in
	command)
		path="$(command -v "$selector")" || path=""
		[[ -z "$path" ]] || paths+=("$path")
		;;
	glob) mapfile -t paths < <(compgen -G "$selector") ;;
	esac
	printf '%s\0' "$kind" "$selector" "${BASH_LINENO[1]:-0}" "${#paths[@]}" "${paths[@]}" >>"$TUNAOS_OWNER_EVENTS"
}

contract_owner_evidence_finish() {
	local rc="$1" result=0
	[[ -n "${TUNAOS_OWNER_EVENTS:-}" ]] || return 0
	python3 "$TUNAOS_OWNER_COLLECTOR" \
		--output "$TUNAOS_CONTRACT_OWNER_EVIDENCE" --source "$TUNAOS_OWNER_SOURCE" \
		--events "$TUNAOS_OWNER_EVENTS" --manager "$TUNAOS_CONTRACT_OWNER_MANAGER" \
		--desktop "$desktop" --exit-code "$rc" --completed "${TUNAOS_OWNER_COMPLETED:-0}" \
		--waived "${TUNAOS_CONTRACT_WAIVED:-0}" || result=$?
	rm -f -- "$TUNAOS_OWNER_EVENTS"
	return "$result"
}
