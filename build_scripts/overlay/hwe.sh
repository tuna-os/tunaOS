#!/usr/bin/env bash

set -euo pipefail

source /run/context/build_scripts/lib.sh

DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export DESKTOP_FLAVOR

printf "::group:: === HWE ===\n"

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	copy_systemfiles_for kde-hwe
	run_buildscripts_for kde-hwe
elif [[ "${DESKTOP_FLAVOR}" == "niri" ]]; then
	copy_systemfiles_for niri-hwe
	run_buildscripts_for niri-hwe
fi

copy_systemfiles_for hwe
run_buildscripts_for hwe

if command -v jq >/dev/null 2>&1; then
	jq . /usr/share/ublue-os/image-info.json || true
else
	cat /usr/share/ublue-os/image-info.json || true
fi
detected_os
printf "::endgroup::\n"
