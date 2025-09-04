#!/usr/bin/env bash

set -euox pipefail
source /run/context/build_scripts/lib.sh

FLAVOR="gdx"
export FLAVOR
"/run/context/build_scripts/scripts/image-info-set"
