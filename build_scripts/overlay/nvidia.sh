#!/usr/bin/env bash

set -euo pipefail

source /run/context/build_scripts/lib.sh

# Set ENABLE_NVIDIA for nvidia-specific scripts
export ENABLE_NVIDIA="${ENABLE_NVIDIA:-1}"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export DESKTOP_FLAVOR

printf "::group:: === nvidia ===\n"

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	copy_systemfiles_for kde-nvidia
	run_buildscripts_for kde-nvidia
elif [[ "${DESKTOP_FLAVOR}" == "niri" ]]; then
	copy_systemfiles_for niri-nvidia
	run_buildscripts_for niri-nvidia
fi

copy_systemfiles_for nvidia
run_buildscripts_for nvidia

# Independent audit of what the overlay just did. run_buildscripts_for
# returns 0 when its overrides directory is missing — exactly how driverless
# "*-nvidia" images shipped for months — so the contract below is a bare call
# under `set -e`: an nvidia overlay that did not actually install the driver
# stack fails the build here rather than publishing. Installed into the image
# too, so desktop-contract-sweep can re-run it against published tags.
/run/context/build_scripts/checks/verify-nvidia.sh
install -Dm0755 /run/context/build_scripts/checks/verify-nvidia.sh \
	/usr/libexec/tunaos/verify-nvidia

if command -v jq >/dev/null 2>&1; then
	jq . /usr/share/ublue-os/image-info.json || true
else
	cat /usr/share/ublue-os/image-info.json || true
fi
detected_os
printf "::endgroup::\n"
