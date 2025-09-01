#!/usr/bin/env bash

set -euox pipefail
source /run/context/build_scripts/lib.sh

dnf -y install \
  uv \
  nvtop
