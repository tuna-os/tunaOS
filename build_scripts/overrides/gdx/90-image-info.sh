#!/usr/bin/env bash

set -euox pipefail
source /run/context/build_scripts/lib.sh

FLAVOR="gdx"
IMAGE_NAME="${IMAGE_NAME}"
IMAGE_REF="ostree-image-signed:docker://ghcr.io/ublue-os/${IMAGE_NAME}"
export FLAVOR
export IMAGE_NAME
export IMAGE_REF
"/run/context/build_scripts/scripts/image-info-set"
