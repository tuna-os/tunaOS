# EL10 block copy plus soft-reboot: hook contract for #4909

EL10 bases stay on xfs, so seed and migrate cannot apply. The install path
copies blocks, then hands control to the installed system without a cold
boot.

## Initrd slot

The #4909 change adds one hook in `hooks/initrd-90medium-install/hooks.d/`.
The initrd calls it with the device node of the booted medium as `$1`. The
hook reads the root and copies it to the target disk. The root is LUKS2, or
plain when the user skips encryption. On CD boots the hook reads it from the
sr0 loop device. On USB boots it reads it from the USB partition.

Rules for the hook:

- Never write the medium.
- Read source blocks from PARTUUID paths only.

## Soft-reboot handoff

After the copy lands, the hook signals the post-install unit. The unit
finishes the target disk. It sets UUIDs and boot config, removes the live
entry and sysext, grows the disk, and adds the firmware entry. Then the
live system calls `systemctl soft-reboot` into the installed root. A soft reboot keeps the
kernel and moves user space to the new root. No firmware pass runs.

## Out of scope

#4909 owns the exact copy tool and the prompt to unlock LUKS. This note
fixes only the slot, the device contract, and the handoff order.
