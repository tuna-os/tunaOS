#!/usr/bin/env bash

# This file is intended to be sourced by other scripts, not executed directly.

set -eo pipefail

# Do not rely on any of these scripts existing in a specific path
# Make the names as descriptive as possible and everything that uses dnf for package installation/removal should have `packages-` as a prefix.

CONTEXT_PATH="$(realpath "$(dirname "$0")/..")" # should return /run/context
BUILD_SCRIPTS_PATH="$(realpath "$(dirname "$0")")"
MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
BASE_IMAGE="$(sh -c '. /usr/lib/os-release ; echo ${BASE_IMAGE}')"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER
export BASE_IMAGE
export IMAGE_VENDOR="tuna-os"


# OS Detection Flags
IS_FEDORA=false
IS_RHEL=false
IS_ALMALINUX=false
IS_ALMALINUXKITTEN=false
IS_CENTOS=false

if [[ "${BASE_IMAGE,,}" == *"fedora"* ]]; then
    IS_FEDORA=true
elif [[ "${BASE_IMAGE,,}" == *"red hat"* ]]; then
    IS_RHEL=true
elif [[ "${BASE_IMAGE,,}" == *"almalinux"* ]]; then
    IS_ALMALINUX=true
elif [[ "${BASE_IMAGE,,}" == *"kitten"* ]]; then
    IS_ALMALINUXKITTEN=true
elif [[ "${BASE_IMAGE,,}" == *"centos"* ]]; then
    IS_CENTOS=true
fi

export IS_FEDORA
export IS_RHEL
export IS_ALMALINUX
export IS_ALMALINUXKITTEN
export IS_CENTOS

get_image_name() {
if [ "$IS_FEDORA" = true ]; then
	IMAGE_NAME="bonito"
	IMAGE_PRETTY_NAME="Bonito"
fi
if [ "$IS_ALMALINUX" = true ] && [ "$IS_ALMALINUXKITTEN" = false ]; then
	IMAGE_NAME="albacore"
	IMAGE_PRETTY_NAME="Albacore"
fi
if [ "$IS_ALMALINUXKITTEN" = true ]; then
	IMAGE_NAME="yellowfin"
	IMAGE_PRETTY_NAME="Yellowfin"
fi
if [ "$IS_CENTOS" = true ] && [ "$IS_ALMALINUXKITTEN" = false ]; then
	IMAGE_NAME="skipjack"
	IMAGE_PRETTY_NAME="Skipjack"
fi
if [ "$IS_RHEL" = true ] && [ "$IS_ALMALINUX" = false ] && [ "$IS_CENTOS" = false ]; then
	IMAGE_NAME="redfin"
	IMAGE_PRETTY_NAME="Redfin"
fi

    export IMAGE_NAME
    export IMAGE_PRETTY_NAME
}

get_image_name 

detected_os() {
	echo "Detected OS:"
	if [ "$IS_FEDORA" = true ]; then
		echo "  Fedora"
	fi
	if [ "$IS_RHEL" = true ]; then
		echo "  RHEL"
	fi
	if [ "$IS_ALMALINUX" = true ]; then
		echo "  AlmaLinux"
	fi
	if [ "$IS_ALMALINUXKITTEN" = true ]; then
		echo "  AlmaLinux-Kitten"
	fi
	if [ "$IS_CENTOS" = true ]; then
		echo "  CentOS"
	fi
}

print_debug_info() {
	detected_os
	echo "IMAGE_NAME: $IMAGE_NAME"
    cat /etc/os-release
    cat /usr/ublue-os/image-info.json || true
}

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
