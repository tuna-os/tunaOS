#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

printf "::group:: === GDX ===\n"

copy_systemfiles_for gdx
run_buildscripts_for gdx
copy_systemfiles_for "$(arch)-gdx"
run_buildscripts_for "$(arch)/gdx"

printf "::endgroup::\n"