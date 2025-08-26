#!/usr/bin/env bash

set -eo pipefail
BASE_IMAGE=$BASE_IMAGE
echo "Running file copy with BASE_IMAGE=${BASE_IMAGE}"
if ! grep -q '^BASE_IMAGE=' /etc/os-release; then
    echo "BASE_IMAGE=\"${BASE_IMAGE}\"" >> /etc/os-release
fi
source /run/context/build_scripts/lib.sh

echo $BASE_IMAGE
cat /etc/os-release

printf "::group:: === Base File Copying ===\n"
cp -avf "/run/context/files/." /
printf "::endgroup::\n"
