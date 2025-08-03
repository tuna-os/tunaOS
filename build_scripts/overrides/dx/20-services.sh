#!/usr/bin/env bash

set -xeuo pipefail

systemctl enable podman.socket
systemctl enable docker.socket
systemctl enable cockpit.socket
systemctl enable libvirtd.service
