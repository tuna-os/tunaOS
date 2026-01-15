#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

# Set ENABLE_GDX for gdx-specific scripts
export ENABLE_GDX="${ENABLE_GDX:-1}"

printf "::group:: === GDX ===\n"

copy_systemfiles_for gdx
run_buildscripts_for gdx

jq . /usr/share/ublue-os/image-info.json
detected_os
printf "::endgroup::\n"
