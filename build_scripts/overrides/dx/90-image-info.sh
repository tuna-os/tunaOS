#!/usr/bin/env bash

set -xeuo pipefail

FLAVOR="dx"
IMAGE_NAME="${IMAGE_NAME}"
IMAGE_REF="ostree-image-signed:docker://ghcr.io/ublue-os/${IMAGE_NAME}"
export FLAVOR
export IMAGE_NAME
export IMAGE_REF
"${SCRIPTS_PATH}/image-info-set"

