#!/usr/bin/env bash

set -euox pipefail
source /run/context/build_scripts/lib.sh
if [ -z "${IMAGE_NAME}" ]; then
	IMAGE_NAME="$(sh -c '. /etc/os-release ; echo ${IMAGE_NAME}')"
fi
FLAVOR="gdx"
export FLAVOR
"/run/context/build_scripts/scripts/image-info-set"
