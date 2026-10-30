#!/usr/bin/env bash

# Validate the serial evidence emitted by the installed desktop contract before
# the qualification result is written. The receipt schema cannot establish
# that the booted guest emitted the expected desktop/session marker.
validate_installed_boot_evidence() {
	local serial="$1"
	local expected_desktop="$2"
	local expected_digest="$3"
	local expected_process_pattern="$4"

	if grep -qF "TUNAOS_DESKTOP_CONTRACT_FAIL" "$serial"; then
		echo "ERROR: installed desktop contract reported failure" >&2
		return 1
	fi
	if ! grep -F "TUNAOS_DESKTOP_CONTRACT_OK desktop=${expected_desktop} " "$serial" |
		grep -F "source_image_digest=${expected_digest}" |
		grep -F "session_class=user" |
		grep -E "session_type=(wayland|x11)" |
		grep -Eq "session_process=(${expected_process_pattern})([[:space:]]|$)"; then
		echo "ERROR: installed desktop, user session, or immutable source identity did not match" >&2
		grep -a "TUNAOS_DESKTOP_CONTRACT_" "$serial" >&2 || true
		return 1
	fi
}
