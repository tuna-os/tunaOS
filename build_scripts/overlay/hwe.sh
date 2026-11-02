#!/usr/bin/env bash

set -euo pipefail

source /run/context/build_scripts/lib.sh

DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export DESKTOP_FLAVOR

printf "::group:: === HWE ===\n"

if command -v jq >/dev/null 2>&1; then
	jq . /usr/share/ublue-os/image-info.json || true
else
	cat /usr/share/ublue-os/image-info.json || true
fi
detected_os
printf "::endgroup::\n"
