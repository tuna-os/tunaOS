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
    # Install from the mounted directory, including the kernel to satisfy dependencies
    dnf versionlock delete kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt || true
    rpms=$(find /tmp/akmods-nvidia-open-rpms/ /tmp/kernel-rpms/ -name "*.rpm" -type f | tr '\n' ' ')
    if [ -n "$rpms" ]; then
        dnf install -y $rpms
    fi
    dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt
fi

printf "::endgroup::\n"
