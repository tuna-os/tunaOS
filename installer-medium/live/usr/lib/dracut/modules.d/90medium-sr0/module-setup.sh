#!/bin/bash
# shellcheck disable=SC2154 # dracut sets $moddir when it sources this file.
# dracut module: expose the medium's partitions on CD boots (tunaOS#4913).
#
# Linux does not scan partitions on sr devices. A CD boot therefore sees no
# PARTUUIDs, and the live entry (root=PARTUUID=) and the installer (CopyBlocks
# from the medium, btrfs seed reads) find nothing. This hook loop-attaches
# /dev/sr0 read-only with partition scan, so the partitions appear as on USB.
check() {
	return 0
}

depends() {
	echo base
	return 0
}

install() {
	inst_hook pre-mount 30 "$moddir/medium-sr0.sh"
	inst_multiple losetup udevadm blkid
}
