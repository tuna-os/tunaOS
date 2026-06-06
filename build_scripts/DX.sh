#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export DESKTOP_FLAVOR

printf "::group:: === DX ===\n"

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	copy_systemfiles_for kde-dx
	run_buildscripts_for kde-dx
elif [[ "${DESKTOP_FLAVOR}" == "niri" ]]; then
	copy_systemfiles_for niri-dx
	run_buildscripts_for niri-dx
fi

copy_systemfiles_for dx
run_buildscripts_for dx

jq . /usr/share/ublue-os/image-info.json
detected_os
printf "::endgroup::\n"
