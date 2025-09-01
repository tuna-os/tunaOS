#!/usr/bin/env bash

# This file needs to exist otherwise running this in a RUN label makes it so bash strict mode doesnt work.
# Thus leading to silent failures

set -eo pipefail
printf "::group:: === Arch Customizations ===\n"

# Do not rely on any of these scripts existing in a specific path
# Make the names as descriptive as possible and everything that uses dnf for package installation/removal should have `packages-` as a prefix.

source /run/context/build_scripts/lib.sh

if [ -d "/run/context/overrides/$(arch)" ]; then
  copy_systemfiles_for "$(arch)"
  run_buildscripts_for "$(arch)"
fi

printf "::endgroup::\n"
