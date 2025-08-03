#!/usr/bin/env bash

set -xeuo pipefail

FLAVOR="gdx"
IMAGE_NAME="yellowfin-${FLAVOR}"
IMAGE_REF="ostree-image-signed:docker://ghcr.io/ublue-os/yellowfin-${FLAVOR}"
export FLAVOR
export IMAGE_NAME
export IMAGE_REF
"${SCRIPTS_PATH}/image-info-set"
