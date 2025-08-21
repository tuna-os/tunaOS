#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

printf "::group:: === DX ===\n"

copy_systemfiles_for dx
run_buildscripts_for dx

jq . /usr/share/ublue-os/image-info.json
printf "::endgroup::\n"