#!/bin/sh
# pre-mount hook: loop-attach the CD-ROM so its partitions appear (tunaOS#4913).
#
# USB boots need nothing: the kernel scans the disk's partitions itself. On a
# CD boot the medium is /dev/sr0, which gets no partition scan, so attach it
# read-only with partition scan. btrfs seed reads (#4908) and block copies
# (#4909) then address the same PARTUUIDs on both boots.
if [ -e /dev/sr0 ] && ! [ -e /dev/disk/by-partuuid ]; then
	if ! losetup -r -P -f /dev/sr0 2>/dev/null; then
		warn "medium-sr0: cannot loop-attach /dev/sr0"
	else
		udevadm settle
	fi
fi
