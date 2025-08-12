#!/usr/bin/env bash

# This file is intended to be sourced by other scripts, not executed directly.

set -eo pipefail

# Do not rely on any of these scripts existing in a specific path
# Make the names as descriptive as possible and everything that uses dnf for package installation/removal should have `packages-` as a prefix.

CONTEXT_PATH="$(realpath "$(dirname "$0")/..")" # should return /run/context
BUILD_SCRIPTS_PATH="$(realpath "$(dirname "$0")")"
MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

IS_FEDORA=false
IS_RHEL=false
IS_ALMALINUX=false
IS_ALMALINUXKITTEN=false
IS_CENTOS=false

if [ "$(rpm -E '%fedora')" != "%fedora" ]; then
	IS_FEDORA=true
fi

if [ "$(rpm -E '%rhel')" != "%rhel" ]; then
	IS_RHEL=true
fi

if [ "$(rpm -E '%almalinux')" != "%almalinux" ]; then
	IS_ALMALINUX=true
fi

if [ "$(rpm -E '%almalinux-kitten')" != "%almalinux-kitten" ]; then
	IS_ALMALINUXKITTEN=true
fi

if [ "$(rpm -E '%centos')" != "%centos" ]; then
	IS_CENTOS=true
fi


run_buildscripts_for() {
	WHAT=$1
	shift
	# Complex "find" expression here since there might not be any overrides
	find "${BUILD_SCRIPTS_PATH}/overrides/$WHAT" -maxdepth 1 -iname "*-*.sh" -type f -print0 | sort --zero-terminated --sort=human-numeric | while IFS= read -r -d $'\0' script; do
		if [ "${CUSTOM_NAME}" != "" ]; then
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
	DISPLAY_NAME=$WHAT
	if [ "${CUSTOM_NAME}" != "" ]; then
		DISPLAY_NAME=$CUSTOM_NAME
	fi
	printf "::group:: ===%s-file-copying===\n" "${DISPLAY_NAME}"
	cp -avf "${CONTEXT_PATH}/overrides/$WHAT/." /
	printf "::endgroup::\n"
}
