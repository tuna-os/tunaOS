#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

# Set ENABLE_GDX for gdx-specific scripts
export ENABLE_GDX="${ENABLE_GDX:-1}"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export DESKTOP_FLAVOR

printf "::group:: === GDX ===\n"

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	copy_systemfiles_for kde-gdx
	run_buildscripts_for kde-gdx
elif [[ "${DESKTOP_FLAVOR}" == "niri" ]]; then
	copy_systemfiles_for niri-gdx
	run_buildscripts_for niri-gdx
fi

copy_systemfiles_for gdx
run_buildscripts_for gdx

jq . /usr/share/ublue-os/image-info.json
detected_os
printf "::endgroup::\n"
