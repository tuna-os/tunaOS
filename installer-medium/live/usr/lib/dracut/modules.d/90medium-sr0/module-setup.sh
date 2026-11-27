#!/bin/bash
# shellcheck disable=SC2154 # dracut sets $moddir when it sources this file.
# dracut module: expose the medium's partitions on CD boots (tunaOS#4913).
#
# Linux does not scan partitions on sr devices. A CD boot therefore sees no
# PARTUUIDs, and the live entry (root=PARTUUID=) and the installer (CopyBlocks
# from the medium, btrfs seed reads) find nothing. A udev rule starts a service
# that loop-attaches the drive read-only with partition scan, so the
# partitions appear as on USB.
check() {
	return 0
}

depends() {
	echo base
	return 0
}

install() {
	inst_script "$moddir/medium-sr0.sh" /usr/libexec/medium-sr0.sh
	inst_simple "$moddir/medium-sr0@.service" /usr/lib/systemd/system/medium-sr0@.service
	inst_rules "$moddir/61-medium-sr0.rules"
	inst_multiple losetup udevadm blkid dd grep
	# The immutable flag of the deployment (medium-live-root.service).
	inst_multiple -o chattr
	# medium-live-cfs.service: remove the composefs image, and report on the console.
	inst_multiple -o rm ls stat
}

installkernel() {
	instmods loop sr_mod cdrom
}
