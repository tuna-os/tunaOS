#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

printf "::group:: === GDX ===\n"

copy_systemfiles_for gdx
run_buildscripts_for gdx

jq . /usr/share/ublue-os/image-info.json
detected_os
printf "::endgroup::\n"
