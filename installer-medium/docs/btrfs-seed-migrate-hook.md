# No-reboot install on btrfs: hook contract for #4908

CI marks the medium root read-only once (`btrfstune -S`). A seed never
changes, so the live system can install from it while it runs.

## Initrd slot

`hooks/initrd-90medium-install/` ships an empty hook directory. The #4908
change adds one executable hook per supported layout. The initrd calls each
hook with the booted medium device node as `$1`. A hook exits 0 when its
payload is staged, or when this boot needs no payload.

Rules for hooks:

- Never write the medium. The seed stays read-only.
- Read source blocks from PARTUUID paths. Both boots expose them: USB
  through the kernel scan, CD through the `90medium-sr0` loop attach.
- Mount the sprout device, never the seed, read-write.

## Post-install slot

`medium-install-post@.service` starts after the copy or migrate step and
waits for no other install step. Each hook in
`/usr/libexec/medium-install-post.d` receives the target disk. Hooks cover,
in order: new filesystem UUIDs; boot-config rewrite (BLS entries, ESP
configs, deployment fstab); live entry and GRUB default removal; sysext
removal from `/var/lib/extensions`; root growth; firmware boot entry.

## Out of scope

Seed creation (`btrfstune -S`) runs in CI at build time. It never runs on
the installed machine.
