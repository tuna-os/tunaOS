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
	inst_multiple losetup udevadm blkid btrfs modprobe findmnt mount
	inst_dir "${moddir}/hooks.d"
	# btrfs seed sprout (#4908): the script and unit run in the initrd.
	inst_script "${moddir}/medium-seed-zram" \
		/usr/lib/dracut/modules.d/90medium-install/medium-seed-zram
	inst_simple "${moddir}/medium-seed-zram.service" \
		"${systemdsystemunitdir}/medium-seed-zram.service"
	$SYSTEMCTL -q --root "$initdir" add-wants initrd-root-fs.target medium-seed-zram.service
}
