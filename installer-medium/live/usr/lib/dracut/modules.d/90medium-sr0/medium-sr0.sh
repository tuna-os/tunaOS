#!/bin/sh
# Loop-attach the disc so that its partitions appear (tunaOS#4913, #4970).
# Run by medium-sr0@.service in the initrd, one instance for each sr device.
#
# USB boots need nothing: the kernel scans the disk's partitions itself. Linux
# scans no partitions on an sr device, so the root of a CD boot never shows up.
# The GPT of the medium counts in blocks of 512 bytes and an sr device has
# blocks of 2048, hence --sector-size. A disc with no GPT is left alone: the
# drive can hold another one.
dev="/dev/${1:?usage: medium-sr0.sh srN}"
dd if="$dev" bs=512 skip=1 count=1 2>/dev/null | grep -q 'EFI PART' || exit 0
losetup --read-only --partscan --sector-size 512 --find "$dev" || exit 1
udevadm settle
