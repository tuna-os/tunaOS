#!/usr/bin/env bash

set -euox pipefail
source /run/context/build_scripts/lib.sh

tee -a /etc/ublue-os/system-flatpaks.list <<EOF
io.podman_desktop.PodmanDesktop
io.github.getnf.embellish
io.github.dvlv.boxbuddyrs
EOF
