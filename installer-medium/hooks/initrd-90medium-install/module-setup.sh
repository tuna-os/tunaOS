#!/bin/bash
# shellcheck disable=SC2154 # dracut sets $moddir when it sources this file.
# dracut module slot: the no-reboot install payload (tunaOS#4908, #4909).
#
# This module ships the hook directory only. The btrfs seed/migrate
# implementation (#4908) and the EL10 block-copy plus soft-reboot path
# (#4909) land their pre-mount hooks in hooks.d/; installer-medium/docs/
# describes the contract each side implements.
check() {
	return 0
}

depends() {
	echo base
	return 0
}

install() {
	inst_multiple losetup udevadm blkid
	inst_dir "${moddir}/hooks.d"
}
