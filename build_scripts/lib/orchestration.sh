#!/usr/bin/env bash

# Build-stage override dispatch and system-file copying.
# This module is sourced by build_scripts/lib.sh; keep it free of source-time
# side effects so callers opt into work explicitly.
run_buildscripts_for() {
	WHAT=$1
	shift
	local override_path="${BUILD_SCRIPTS_PATH}/overrides/$WHAT"
	if [ ! -d "$override_path" ]; then
		echo "No build script overrides for '$WHAT', skipping."
		return 0
	fi
	# Complex "find" expression here since there might not be any overrides
	find "$override_path" -maxdepth 1 -iname "*-*.sh" -type f -print0 | sort --zero-terminated --sort=human-numeric | while IFS= read -r -d $'\0' script; do
		if [ "${CUSTOM_NAME:-}" != "" ]; then
			WHAT=$CUSTOM_NAME
		fi
		printf "::group:: ===$WHAT-%s===\n" "$(basename "$script")"
		"$(realpath "$script")"
		printf "::endgroup::\n"
	done
}

copy_systemfiles_for() {
	WHAT=$1
	shift
	local override_path="${CONTEXT_PATH}/overrides/$WHAT"
	DISPLAY_NAME=$WHAT
	if [ "${CUSTOM_NAME:-}" != "" ]; then
		DISPLAY_NAME=$CUSTOM_NAME
	fi
	if [ ! -d "$override_path" ]; then
		echo "No system file overrides for '$WHAT', skipping."
		return 0
	fi
	printf "::group:: ===%s-file-copying===\n" "${DISPLAY_NAME}"
	cp -rvf "$override_path/." / || cp -rf "$override_path/." / || true
	printf "::endgroup::\n"
}
