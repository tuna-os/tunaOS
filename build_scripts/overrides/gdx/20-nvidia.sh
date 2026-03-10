#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 20 NVIDIA & CUDA ===\n"

source /run/context/build_scripts/lib.sh

if [[ "${ENABLE_HWE:-0}" != "1" ]] && { [[ $IS_ALMALINUX == true ]] || [[ $IS_ALMALINUXKITTEN == true ]]; }; then
    # AlmaLinux gets nvidia from the alma repos (signed with AlmaLinux Secure Boot key)
    dnf install -y almalinux-release-nvidia-driver
    
    # Install nvidia driver that works with current kernel
    # Use --nobest --skip-broken to allow DNF to find compatible versions
    dnf -y install --nobest --skip-broken \
        nvidia-driver \
        nvidia-driver-cuda-libs || echo "Warning: Some NVIDIA packages failed to install, hardware may not be supported"
    
    # Add official NVIDIA CUDA repository for EL
    dnf config-manager --add-repo "https://developer.download.nvidia.com/compute/cuda/repos/rhel${MAJOR_VERSION_NUMBER}/x86_64/cuda-rhel${MAJOR_VERSION_NUMBER}.repo"
    
    # Install CUDA toolkit from official NVIDIA repo
    dnf -y install cuda-toolkit
else
    # Fedora/CentOS from akmods
    # Install from the mounted directory, including the kernel to satisfy dependencies
    dnf versionlock delete kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt || true
    rpms=$(find /tmp/akmods-nvidia-open-rpms/ /tmp/kernel-rpms/ -name "*.rpm" -type f | tr '\n' ' ')
    if [ -n "$rpms" ]; then
        # Mask rpm-ostree kernel-install script to prevent dracut errors during container build
        mv /usr/lib/kernel/install.d/05-rpmostree.install /tmp/05-rpmostree.install.bak || true
        dnf install -y $rpms
        mv /tmp/05-rpmostree.install.bak /usr/lib/kernel/install.d/05-rpmostree.install || true
    fi
    dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt
fi

printf "::endgroup::\n"
