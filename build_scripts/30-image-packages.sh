#!/usr/bin/env bash
# Install this variant's image-wide package additions from tunaos.toml.
#
# Runs in the base stage of every Containerfile, after the base packages, so
# every flavor built on that base has them (Gentoo's desktop chain does not
# descend from its base stage and runs this too). A variant with no
# additions exits before lib.sh is sourced: nothing runs, nothing is written.
set -euo pipefail

lib=/run/context/build_scripts/lib
# shellcheck source=lib/image-packages.sh
source "${lib}/image-packages.sh"
variant="${IMAGE_NAME_VARIANT:-${IMAGE_NAME:-}}"
if [[ -z "$(tunaos_image_package_rows "$lib" "$variant")" ]]; then
	echo "image packages: none for ${variant:-this image} in tunaos.toml"
	exit 0
fi

# shellcheck source=lib.sh
source /run/context/build_scripts/lib.sh
tunaos_apply_image_packages "$lib"
