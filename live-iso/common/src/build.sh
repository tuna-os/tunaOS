#!/usr/bin/bash

set -exo pipefail

# Create the directory that /root is symlinked to
mkdir -p "$(realpath /root)"

# Install requirements.
# If on RHEL-based systems, we might need EPEL for some packages.
if [ -f /etc/redhat-release ] && ! grep -q "Fedora" /etc/redhat-release; then
	dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-10.noarch.rpm || true
fi

# Install dracut-live and regenerate the initramfs
dnf install -y dracut-live jq
kernel=$(kernel-install list --json pretty | jq -r '.[] | select(.has_kernel == true) | .version' | head -n 1)
if [ -z "$kernel" ]; then
	# Fallback for some distros where kernel-install might not list kernels
	kernel=$(find /lib/modules -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | head -n 1)
	fi
DRACUT_NO_XATTR=1 dracut -v --force --zstd --reproducible --no-hostonly \
	--add "dmsquash-live dmsquash-live-autooverlay" \
	"/usr/lib/modules/${kernel}/initramfs.img" "${kernel}"

# Install livesys-scripts and configure them
dnf install -y livesys-scripts
sed -i "s/^livesys_session=.*/livesys_session=${DESKTOP_FLAVOR:-gnome}/" /etc/sysconfig/livesys
systemctl enable livesys.service livesys-late.service

# image-builder needs gcdx64.efi
dnf install -y grub2-efi-x64-cdboot

# image-builder expects the EFI directory to be in /boot/efi
mkdir -p /boot/efi
# In some distros it's /usr/lib/efi, in others it might be different
EFI_SOURCE=""
if [ -d /usr/lib/efi ]; then
	EFI_SOURCE="/usr/lib/efi"
elif [ -d /usr/share/grub ]; then
	EFI_SOURCE="/usr/share/grub"
fi

if [ -n "$EFI_SOURCE" ]; then
	cp -av "$EFI_SOURCE"/*/*/EFI /boot/efi/ || true
fi

# needed for image-builder's buildroot
dnf install -y xorriso isomd5sum squashfs-tools

# Clean up dnf cache to save space
dnf clean all
