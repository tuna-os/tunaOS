# No-reboot install on btrfs: hook contract for #4908

CI marks the medium root read-only once (`btrfstune -S`). A seed never
changes, so the live system can install from it while it runs.

## Initrd slot

`hooks/initrd-90medium-install/` ships an empty hook directory. The #4908
change adds one executable hook per supported layout. The initrd calls each
hook with the device node of the booted medium as `$1`. A hook exits 0 when
it has staged its payload, or when this boot needs no payload.

Rules for hooks:

- Never write the medium. The seed stays read-only.
- Read source blocks from PARTUUID paths. Both boots expose them: USB
  through the kernel scan, CD through the `90medium-sr0` loop attach.
- Mount the sprout device, never the seed, read-write.

## Post-install slot

`medium-install-post@.service` starts after the copy or migrate step and
waits for no other install step. Each hook in
`/usr/libexec/medium-install-post.d` receives the target disk. Hooks do these steps in order:

1. Set new filesystem UUIDs.
2. Rewrite the boot config (BLS entries, ESP configs, deployment fstab).
3. Remove the live entry and the GRUB default.
4. Remove the sysext from `/var/lib/extensions`.
5. Grow the root.
6. Add the firmware boot entry.

## Implemented so far (#4908)

- `hooks/initrd-90medium-install/medium-seed-zram` and its unit add a zram
  device to the mounted seed after `sysroot.mount` and before
  `bootc-root-setup.service` and `ostree-prepare-root.service`. It does
  nothing off the live medium or on a non-seed root.
- `hooks/medium-migrate-btrfs TARGET_DEV` runs `btrfs device add` on the
  unlocked target, then removes zram and the seed through `/var`.

Not yet done, and not tested on a VM:

- the `io.tunaos.Install.Migrate` Varlink service
- fs-verity and the strict loader entry for composefs
- the firmware boot entry
- ostree on a seed
- the QEMU + swtpm + Secure Boot run that the issue names as done

## Out of scope

Seed creation (`btrfstune -S`) runs in CI at build time. It never runs on
the installed machine.
