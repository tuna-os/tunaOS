#!/usr/bin/env bash
# Preserve package intent and command results across build RUN/overlay stages.
# Python-free phases leave an explicit coverage marker for the final verifier.

_tunaos_record_gap() {
	local ledger="$1" reason="$2"
	# Failure to record must not replace the native command's exit status.
	# Missing or unfinished ledgers still block the final contract verifier.
	mkdir -p "${ledger%/*}" 2>/dev/null && printf '%s\n' "$reason" >>"${ledger}.gaps" 2>/dev/null || true
}

_tunaos_package_command() {
	local manager="${1:?manager required}"
	shift
	if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" != 1 ]]; then
		command "$manager" "$@"
		return $?
	fi
	local ledger="${TUNAOS_PACKAGE_LEDGER:-/usr/share/tunaos/evidence/package-requests.jsonl}"
	local recorder="${TUNAOS_PACKAGE_RECORDER:-${CONTEXT_PATH:-/run/context}/build_scripts/package_requests.py}"
	local request_id="" rc=0
	local origin="${BASH_SOURCE[2]:-unknown}" line="${BASH_LINENO[1]:-0}"
	if command -v python3 >/dev/null 2>&1 && [[ -r "$recorder" ]]; then
		request_id="$(python3 "$recorder" --ledger "$ledger" start --manager "$manager" --origin "$origin" --line "$line" -- "$@" 2>/dev/null)" || {
			_tunaos_record_gap "$ledger" request-recording-failed
		}
	else
		_tunaos_record_gap "$ledger" request-recorder-unavailable
	fi
	# `command` bypasses the recording function but retains the installed tool
	# or test stub. Its result always determines the wrapper's result.
	command "$manager" "$@" || rc=$?
	if [[ -n "$request_id" ]]; then
		python3 "$recorder" --ledger "$ledger" finish --request-id "$request_id" --exit-code "$rc" 2>/dev/null || {
			_tunaos_record_gap "$ledger" request-result-recording-failed
		}
	fi
	return "$rc"
}

# Preserve command availability: defining a dnf function on an APT base would
# make existing `command -v dnf` probes select the wrong manager.
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P dnf >/dev/null; then
	dnf() { _tunaos_package_command dnf "$@"; }
	export -f dnf
fi
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P dnf5 >/dev/null; then
	dnf5() { _tunaos_package_command dnf5 "$@"; }
	export -f dnf5
fi
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P apt >/dev/null; then
	apt() { _tunaos_package_command apt "$@"; }
	export -f apt
fi
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P apt-get >/dev/null; then
	apt-get() { _tunaos_package_command apt-get "$@"; }
	export -f apt-get
fi
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P pacman >/dev/null; then
	pacman() { _tunaos_package_command pacman "$@"; }
	export -f pacman
fi
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P zypper >/dev/null; then
	zypper() { _tunaos_package_command zypper "$@"; }
	export -f zypper
fi
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P emerge >/dev/null; then
	emerge() { _tunaos_package_command emerge "$@"; }
	export -f emerge
fi
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P rpm >/dev/null; then
	rpm() { _tunaos_package_command rpm "$@"; }
	export -f rpm
fi
if [[ "${TUNAOS_RECORD_PACKAGE_REQUESTS:-0}" == 1 ]] && type -P dpkg >/dev/null; then
	dpkg() { _tunaos_package_command dpkg "$@"; }
	export -f dpkg
fi
export -f _tunaos_package_command _tunaos_record_gap
