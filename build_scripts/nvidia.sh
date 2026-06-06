#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

# Set ENABLE_NVIDIA for nvidia-specific scripts
export ENABLE_NVIDIA="${ENABLE_NVIDIA:-1}"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export DESKTOP_FLAVOR

printf "::group:: === NVIDIA ===\n"

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	copy_systemfiles_for kde-nvidia
	run_buildscripts_for kde-nvidia
elif [[ "${DESKTOP_FLAVOR}" == "niri" ]]; then
	copy_systemfiles_for niri-nvidia
	run_buildscripts_for niri-nvidia
fi

copy_systemfiles_for nvidia
run_buildscripts_for nvidia

jq . /usr/share/ublue-os/image-info.json
detected_os
printf "::endgroup::\n"
