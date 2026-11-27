#!/bin/sh
# Loop-attach the disc so that its partitions appear (tunaOS#4913, #4970).
# Run by medium-sr0@.service in the initrd, one instance for each sr device.
#
# USB boots need nothing: the kernel scans the disk's partitions itself. Linux
# scans no partitions on an sr device, so the root of a CD boot never shows up.
# The GPT of the medium counts in blocks of 512 bytes and an sr device has
# blocks of 2048, hence --sector-size. A disc with no GPT is left alone: the
# drive can hold another one. The test is the result, not a read of the
# signature: the kernel scans the partitions while losetup attaches the disc,
# and a disc that has no partition 1 is detached again. The initrd of a GNOME
# OS image (Brussels) has losetup but no dd, so this needs nothing else.
dev="/dev/${1:?usage: medium-sr0.sh srN}"
loop="$(losetup --read-only --partscan --sector-size 512 --find --show "$dev")" || exit 1
udevadm settle
name="${loop##*/}"
if [ ! -e "${SYS_CLASS_BLOCK:-/sys/class/block}/${name}p1" ]; then
	losetup --detach "$loop"
fi
