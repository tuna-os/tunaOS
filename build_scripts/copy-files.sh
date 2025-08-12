#!/usr/bin/env bash

set -eo pipefail

source /run/context/build_scripts/lib.sh

printf "::group:: === Base File Copying ===\n"
cp -avf "/run/context/files/." /
printf "::endgroup::\n"
