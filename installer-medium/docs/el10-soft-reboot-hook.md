# EL10 block copy plus soft-reboot: hook contract for #4909

EL10 bases stay on xfs, so seed and migrate cannot apply. The install path
copies blocks, then hands control to the installed system without a cold
boot.

## Initrd slot

The #4909 change adds one hook in `hooks/initrd-90medium-install/hooks.d/`.
The initrd calls it with the booted medium device node as `$1`. The hook
reads the LUKS2 root (or plain root when the user skips encryption) from
the sr0 loop device on CD boots, or from the USB partition on USB boots,
and copies it to the target disk.

Rules for the hook:

- Never write the medium.
- Read source blocks from PARTUUID paths only.

## Soft-reboot handoff

After the copy lands, the hook signals the post-install unit. The unit
finishes the target disk (UUIDs, boot config, live entry removal, sysext
removal, growth, firmware entry), then the live system calls
`systemctl soft-reboot` into the installed root. A soft reboot keeps the
kernel and moves user space to the new root. No firmware pass runs.

## Out of scope

The exact copy tool and the LUKS unlock prompt belong to #4909. This note
fixes only the slot, the device contract, and the handoff order.
