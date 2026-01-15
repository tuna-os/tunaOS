#!/usr/bin/env bash

set -euox pipefail

source /run/context/build_scripts/lib.sh

KERNEL_SUFFIX=""
QUALIFIED_KERNEL="$(rpm -qa | grep -P 'kernel-(|'"$KERNEL_SUFFIX"'-)(\d+\.\d+\.\d+)' | sed -E 's/kernel-(|'"$KERNEL_SUFFIX"'-)//' | tail -n 1)"

# Get Kernel Version for akmods
KERNEL_NAME="kernel"
KERNEL_VRA="$(rpm -q "$KERNEL_NAME" --queryformat '%{EVR}.%{ARCH}')"

# Detect architecture for NVIDIA repo
ARCH="$(uname -m)"
if [ "$ARCH" = "aarch64" ]; then
	NVIDIA_ARCH="sbsa"
else
	NVIDIA_ARCH="$ARCH"
fi

##############################
# Nvidia install for AlmaLinux
##############################

if [ "$IS_ALMALINUX" == true ]; then
	dnf config-manager --set-disabled "epel-multimedia" || true
	dnf install -y almalinux-release-nvidia-driver
	dnf install -y nvidia-open-kmod nvidia-driver
	dnf install -y nvidia-driver-cuda cuda
	dnf config-manager --set-disabled "almalinux-nvidia"
	if [ "$(arch)" != "aarch64" ]; then
		dnf config-manager --set-disabled "cuda-rhel10-$(arch)"
	fi
fi

##############################
# Nvidia install for CentOS with HWE support
##############################

if [ "$IS_CENTOS" == true ] && [ "$IS_ALMALINUX" == false ]; then
	# Check if we should use HWE akmods (pre-built from coreos-stable)
	USE_AKMODS="${ENABLE_GDX:-0}"

	if [ "$USE_AKMODS" == "1" ] && [ -d "/tmp/akmods-nvidia-open-rpms" ]; then
		# HWE path: Use pre-built akmods from ublue-os/akmods-nvidia-open
		echo "Installing NVIDIA drivers from pre-built akmods..."

		FEDORA_VERSION=43 # FIXME: Figure out a way of fetching this information with coreos akmods as well.

		curl -fsSLo - "https://negativo17.org/repos/fedora-nvidia.repo" | sed "s/\$releasever/${FEDORA_VERSION}/g" | tee "/etc/yum.repos.d/fedora-nvidia.repo"
		dnf config-manager --set-disabled "fedora-nvidia"

		# Install NVIDIA driver packages and dependencies
		dnf -y install --enablerepo="fedora-nvidia" \
			/tmp/akmods-nvidia-open-rpms/kmods/kmod-nvidia-"${KERNEL_VRA}"-*.rpm \
			/tmp/akmods-nvidia-open-rpms/ublue-os/*.rpm
		dnf config-manager --set-enabled "nvidia-container-toolkit"

		# Get the kmod-nvidia version to ensure driver packages match
		KMOD_VERSION="$(rpm -q --queryformat '%{VERSION}' kmod-nvidia)"
		# Determine the expected package version format (epoch:version-release)
		NVIDIA_PKG_VERSION="3:${KMOD_VERSION}-1.fc${FEDORA_VERSION}"

		dnf install -y --enablerepo="fedora-nvidia" \
			"libnvidia-fbc-${NVIDIA_PKG_VERSION}" \
			"libnvidia-ml-${NVIDIA_PKG_VERSION}" \
			"nvidia-driver-${NVIDIA_PKG_VERSION}" \
			"nvidia-driver-cuda-${NVIDIA_PKG_VERSION}" \
			"nvidia-settings-${NVIDIA_PKG_VERSION}" \
			nvidia-container-toolkit

		# Ensure the version of the Nvidia module matches the driver
		DRIVER_VERSION="$(rpm -q --queryformat '%{VERSION}' nvidia-driver)"
		if [ "$KMOD_VERSION" != "$DRIVER_VERSION" ]; then
			echo "Error: kmod-nvidia version ($KMOD_VERSION) does not match nvidia-driver version ($DRIVER_VERSION)"
			exit 1
		fi

		# nvidia post-install steps
		# disable repos provided by ublue-os-nvidia-addons
		dnf config-manager --set-disabled nvidia-container-toolkit

		systemctl enable ublue-nvctk-cdi.service
		semodule --verbose --install /usr/share/selinux/packages/nvidia-container.pp

		# Universal Blue specific Initramfs fixes
		cp /etc/modprobe.d/nvidia-modeset.conf /usr/lib/modprobe.d/nvidia-modeset.conf
		# we must force driver load to fix black screen on boot for nvidia desktops
		sed -i 's@omit_drivers@force_drivers@g' /usr/lib/dracut/dracut.conf.d/99-nvidia.conf
		# as we need forced load, also must pre-load intel/amd iGPU else chromium web browsers fail to use hardware acceleration
		sed -i 's@ nvidia @ i915 amdgpu nvidia @g' /usr/lib/dracut/dracut.conf.d/99-nvidia.conf

	else
		# Standard path: Build nvidia drivers using DKMS
		echo "Installing NVIDIA drivers using DKMS..."

		# Add negativo17 repo for NVIDIA drivers (kmod)
		dnf config-manager --add-repo="https://negativo17.org/repos/epel-nvidia.repo"
		dnf config-manager --set-disabled "epel-nvidia"
		# Set lower priority for negativo17 repo
		dnf config-manager setopt epel-nvidia.priority=50

		# Add official NVIDIA CUDA repository for CentOS/RHEL 10
		dnf config-manager --add-repo="https://developer.download.nvidia.com/compute/cuda/repos/rhel10/x86_64/cuda-rhel10.repo"
		dnf config-manager --set-disabled "cuda-rhel10-x86_64"
		# Set higher priority for official NVIDIA CUDA repo and exclude kmod packages
		dnf config-manager setopt cuda-rhel10-x86_64.priority=10
		dnf config-manager setopt cuda-rhel10-x86_64.excludepkgs=kmod-nvidia-latest-dkms

		# These are necessary for building the nvidia drivers
		# Also make sure the kernel is locked before this is run whenever the kernel updates
		# kernel-devel might pull in an entire new kernel if you dont do
		dnf versionlock delete kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt
		dnf install -y "kernel-devel-$QUALIFIED_KERNEL" "kernel-headers-$QUALIFIED_KERNEL" dkms gcc-c++
		dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt

		# Install NVIDIA drivers from negativo17 and CUDA from official NVIDIA repo
		dnf install -y --enablerepo="epel-nvidia" \
			nvidia-driver{,-cuda} dkms-nvidia

		dnf install -y --enablerepo="cuda-rhel10-x86_64" \
			cuda

		sed -i -e 's/kernel$/kernel-open/g' /etc/nvidia/kernel.conf
		cat /etc/nvidia/kernel.conf

		# The nvidia-open driver tries to use the kernel from the host. (uname -r), just override it and let it do whatever otherwise
		# FIXME: remove this workaround please at some point
		cat >/tmp/fake-uname <<EOF
#!/usr/bin/env bash

if [ "\$1" == "-r" ] ; then
  echo ${QUALIFIED_KERNEL}
  exit 0
fi

exec /usr/bin/uname \$@
EOF
		install -Dm0755 /tmp/fake-uname /tmp/bin/uname

		NVIDIA_DRIVER_VERSION="$(rpm -q dkms-nvidia --queryformat="%{VERSION}")"
		PATH=/tmp/bin:$PATH dkms --force install -m nvidia -v "$NVIDIA_DRIVER_VERSION" -k "$QUALIFIED_KERNEL"
		cat "/var/lib/dkms/nvidia/$NVIDIA_DRIVER_VERSION/build/make.log" || echo "Expected failure"
	fi

	# Common configuration for both paths
	cat >/usr/lib/modprobe.d/00-nouveau-blacklist.conf <<EOF
blacklist nouveau
options nouveau modeset=0
EOF

	cat >/usr/lib/bootc/kargs.d/00-nvidia.toml <<EOF
kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1"]
EOF
fi

#################
# End of CentOS #
#################

# Make sure initramfs is rebuilt after nvidia drivers or kernel replacement
mkdir -p /var/tmp
/usr/bin/dracut --no-hostonly --kver "$QUALIFIED_KERNEL" --reproducible --zstd -v -f
