#!/usr/bin/env bash

set -euox pipefail
source /run/context/build_scripts/lib.sh

systemctl enable podman.socket
systemctl enable docker.socket
systemctl enable cockpit.socket
systemctl enable libvirtd.service
