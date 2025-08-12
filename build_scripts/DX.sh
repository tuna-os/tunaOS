#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

printf "::group:: === DX ===\n"

copy_systemfiles_for dx
run_buildscripts_for dx
copy_systemfiles_for "$(arch)-dx"
run_buildscripts_for "$(arch)/dx"

printf "::endgroup::\n"