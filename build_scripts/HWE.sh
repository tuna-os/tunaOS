#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

printf "::group:: === HWE ===\n"

copy_systemfiles_for hwe
run_buildscripts_for hwe

jq . /usr/share/ublue-os/image-info.json
detected_os
printf "::endgroup::\n"
