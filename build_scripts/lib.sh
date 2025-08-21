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

# OS Detection Flags
IS_FEDORA=false
IS_RHEL=false
IS_ALMALINUX=false
IS_ALMALINUXKITTEN=false
IS_CENTOS=false
IS_UBUNTU=false
IS_DEBIAN=false

# Detect using /etc/os-release if available
if [ -f /etc/os-release ]; then
	. /etc/os-release
	case "$ID" in
		fedora)
			IS_FEDORA=true
			;;
		rhel)
			IS_RHEL=true
			;;
		almalinux)
			IS_ALMALINUX=true
			;;
		centos)
			IS_CENTOS=true
			;;
		ubuntu)
			IS_UBUNTU=true
			;;
		debian)
			IS_DEBIAN=true
			;;
	esac
	# Handle variants
	if [[ "$ID_LIKE" == *rhel* ]]; then
		IS_RHEL=true
	fi
	if [[ "$ID" == "almalinux-kitten" ]]; then
		IS_ALMALINUXKITTEN=true
	fi
else
	# Fallback to rpm macros if /etc/os-release is missing
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
fi

is_fedora() { [ "$IS_FEDORA" = true ]; }
is_rhel() { [ "$IS_RHEL" = true ]; }
is_almalinux() { [ "$IS_ALMALINUX" = true ]; }
is_almalinuxkitten() { [ "$IS_ALMALINUXKITTEN" = true ]; }
is_centos() { [ "$IS_CENTOS" = true ]; }
is_ubuntu() { [ "$IS_UBUNTU" = true ]; }
is_debian() { [ "$IS_DEBIAN" = true ]; }


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

install_from_copr() {
    CO_PR_NAME=$1
    shift
    dnf -y copr enable "$CO_PR_NAME"
    dnf -y --enablerepo "copr:copr.fedorainfracloud.org:$(echo "$CO_PR_NAME" | tr '/' ':')" install "$@"
    dnf -y copr disable "$CO_PR_NAME"
}
