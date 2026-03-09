#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export DESKTOP_FLAVOR

printf "::group:: === HWE ===\n"

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	copy_systemfiles_for kde-hwe
	run_buildscripts_for kde-hwe
fi

copy_systemfiles_for hwe
run_buildscripts_for hwe

jq . /usr/share/ublue-os/image-info.json
detected_os
printf "::endgroup::\n"
