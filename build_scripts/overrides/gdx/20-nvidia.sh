#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 20 NVIDIA & CUDA ===\n"

source /run/context/build_scripts/lib.sh

if [[ $IS_ALMALINUX == true ]] || [[ $IS_ALMALINUXKITTEN == true ]]; then
    # AlmaLinux gets nvidia from the alma repos
    dnf install -y almalinux-release-nvidia-driver
    dnf -y install \
        nvidia-driver \
        cuda \
        nvidia-driver-cuda
else
    # Fedora/CentOS from akmods
    # Install from the mounted directory
    find /tmp/akmods-nvidia-open-rpms/ -name "*.rpm" -exec dnf install -y {} +
fi

printf "::endgroup::\n"
