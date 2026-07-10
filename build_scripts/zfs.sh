#!/usr/bin/env bash
# zfs.sh — bake ZFS root support into an image (Ubuntu/apt only; grouper's
# gnome-zfs flavor). Runs BEFORE finalize.sh, because finalize.sh builds the
# dracut initramfs and then bootcifies the rootfs (apt is unusable afterwards).
#
# NOTE: this only makes the image *capable* of a ZFS root. bootc has no
# `install to-disk --filesystem zfs` (only xfs/ext4/btrfs); a ZFS root is
# installed with `bootc install to-filesystem` onto a pre-created zpool, and —
# because the default composefs backend needs fs-verity, which ZFS lacks — a
# non-composefs / --allow-missing-verity deployment. See tuna-os/tunaOS#625.

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

if [[ "$PKG_MGR" != "apt" ]]; then
	echo "zfs.sh: ZFS root support is only implemented for apt (Ubuntu) images; skipping"
	exit 0
fi

export DEBIAN_FRONTEND=noninteractive

# The image's kernel version — the prebuilt ZFS module is version-locked to it.
KVER="$(ls /usr/lib/modules | sort -V | tail -1)"
echo "zfs.sh: targeting kernel ${KVER}"

apt-get update -qq

# - linux-modules-extra-<kver>: Ubuntu's prebuilt, signed zfs.ko (no DKMS).
# - zfsutils-linux:             zfs/zpool userspace.
# - zfs-dracut:                 the dracut 90zfs module (grouper builds its
#                               initramfs with dracut in finalize.sh, not
#                               initramfs-tools, so zfs-initramfs is the wrong
#                               integration here).
pkg_install \
	"linux-modules-extra-${KVER}" \
	zfsutils-linux \
	zfs-dracut

# Load zfs early.
echo zfs >/etc/modules-load.d/zfs.conf

# zfs-dracut must have dropped the 90zfs module — dracut in finalize.sh fails
# with "Module 'zfs' cannot be found" otherwise. Verify loudly rather than ship
# a non-bootable ZFS initramfs.
if [[ ! -d /usr/lib/dracut/modules.d/90zfs ]]; then
	echo "ERROR: zfs-dracut did not install the dracut 90zfs module" >&2
	exit 1
fi

# finalize.sh runs `dracut --no-hostonly`, which won't auto-detect a ZFS root
# at image-build time, so force the zfs module into every initramfs it builds.
# (Mirrors the proven approach in tuna-os/ubuntu, which passes
# `dracut --add "dmsquash-live zfs"`.)
mkdir -p /etc/dracut.conf.d
printf 'add_dracutmodules+=" zfs "\n' >/etc/dracut.conf.d/90-tunaos-zfs.conf

depmod "${KVER}" || true

echo "zfs.sh: ZFS module + tools + dracut 90zfs module wired for ${KVER}"
echo "zfs.sh: finalize.sh will build a ZFS-capable initramfs; the ZFS-root"
echo "        installer ships at /usr/local/bin/zfs-install (from tuna-os/ubuntu)."
