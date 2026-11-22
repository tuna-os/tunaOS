# installer-medium: build the hybrid installer medium

CI builds the hybrid medium once per cell and publishes it as an OCI image
for the installer. CI signs the image. Builders only fetch, verify, and write it. Never run
an image build locally; CI owns `bootc install`, `systemd-repart`, and
`btrfstune -S`.

## Cells

`[installer_medium.cells]` in `tunaos.toml` declares each cell: filesystem,
bootloader, and bootc backend. Two cells anchor the matrix:

| Cell | Filesystem | Bootloader | Backend |
|---|---|---|---|
| `albacore:gnome` | xfs (EL10) | GRUB | ostree |
| `tromso:kde` | btrfs | systemd-boot | composefs |

`scripts/lib/installer_medium.py` validates the table. Send config questions

## Build flow

```bash
installer-medium/build-medium.sh CELL OUT.ISO [--dry-run]
```

Steps in order:

1. `build-live-image.sh`: podman builds `Containerfile.live` FROM the cell
   ref. The live layer carries skip drop-ins, the live setup, and the
   dracut config. It never alters the deployed image behavior: each unit
   keys off `tunaos.live`.
2. `build-to-disk.sh`: `bootc install to-disk` writes the live layer image
   to a blank disk with the cell backend and bootloader.
3. `add-live-entry.sh`: writes the live boot entry. GRUB cells get a BLS
   entry, and copies of the kernel and initrd on the ESP. Systemd-boot cells get a
   Type #1 entry plus the live-only initrd (Dakota pattern).
4. `sysext/build-sysext.sh` + `place-sysext.sh`: the sysext
   with the pinned systemd goes into `/var/lib/extensions` on the medium.
5. `repart/build-hybrid.sh`: `systemd-repart --el-torito=yes` copies each
   partition with `CopyBlocks=` into the hybrid file. One file boots as CD
   and as dd-written USB.
6. `flatpak/bake-flatpaks.sh`: bakes the fixed set from
   `[flatpak_preinstall]`, then `scripts/check-flatpak-medium.py` proves
   the set equals the generated policy.
7. `publish/chunk-publish.py`: chunks, compresses, and writes the OCI
   layout that `tacklebox write-medium` reads.

`--dry-run` prints each step and touches nothing. The test suite drives it
without root.

## CD boot support

Linux does not scan `sr` devices for partitions. The `90medium-sr0` dracut
module attaches `/dev/sr0` as a read-only loop device and scans it for
partitions. PARTUUID paths then resolve on both boots.

## Hooks for #4908 and #4909

- `hooks/initrd-90medium-install/`: initrd module slot for the seed,
  migrate, copy, and soft-reboot payload.
- `hooks/medium-install-post`, `medium-install-post@.service`: target-disk
  finish step that gnome-setup starts.
- `docs/btrfs-seed-migrate-hook.md`, `docs/el10-soft-reboot-hook.md`:
  the contracts that each issue makes.

## Boundaries

- `.github/workflows/` belongs to the CI session.
- `installer-medium/frontends/` belongs to the gnome session.
- Never post the vendored patch upstream; systemd#44968 carries it.
