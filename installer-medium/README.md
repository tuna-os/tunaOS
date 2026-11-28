# installer-medium: build the hybrid installer medium

CI builds the hybrid medium once per cell and publishes it as an OCI image
for the installer. CI signs the image. Builders only fetch, verify, and write it. Never run
an image build locally; CI owns `bootc install`, `systemd-repart`, and
`btrfstune -S`.

## Cells

Every variant:flavor of the `tunaos.toml` matrix resolves to one medium cell.
`scripts/lib/installer_medium.py` computes each row by rule, so the cells
cannot drift from the matrix. [`docs/cells.md`](docs/cells.md) is the
generated table.

| Field | Source |
|---|---|
| Frontend | `[installer_medium.frontends]` maps the desktop of the flavor to a directory in `frontends/`. The desktop is the flavor up to its first dash: `kde-nvidia` uses `kde`. |
| Bootloader, backend | The installer recipe probe on the published image, recorded in `evidence/images.json`. |
| Filesystem | The same probe with the btrfs opt-in. EL bases get xfs. Other bases get btrfs. A composefs image on a kernel older than 7.4-rc2 gets ext4. |
| Architectures | `platforms` of the flavor, else of the variant. |

Each cell has one status:

- `promoted`: supported, and in the nightly. `promoted = true` in
  `[[installer_medium.cells]]` sets it. Seven cells have it:
  `albacore:gnome`, `tromso:kde` and `bonito:{gnome,kde,cosmic,niri,xfce}`.
- `supported`: the evidence gives a layout. Dispatch the workflow with the
  cell name to build it.
- `unverified`: no image, an image that the scan cannot read, or a flavor
  that is not built. The row states the reason. A build stops with that
  reason. The resolver guesses nothing from a name.
- `no-medium`: a `base` flavor. It has no graphical session, so it has no
  installer on screen. Install it with `bootc install` or a disk image.

### Evidence

```bash
installer-medium/evidence/scan-images.py [--cell CELL]...
scripts/gen-installer-medium-cells.py
```

`scan-images.py` reads each layer of each published image from the
registry. It keeps only the paths that the probe reads, then runs
`live-iso/common/src/installer-recipe-backend.sh` on that tree. It writes the
result with the image digest and the date. Only this script uses the network.
Run it again when an image changes its bootloader or backend, then generate
the table. `verify-cell-layout.sh` runs the probe again inside the image at
build time and stops the build on a difference.

An image can carry the probe inputs in the label
`org.tunaos.installer.probe`. The script reads that label from the image
config first, and reads the layers only when the label is absent or not
valid. `--layer-scan` ignores the label. No published image has the label
yet: [docs/probe-label.md](docs/probe-label.md) has the design and the
rollout steps.

`tests/test_installer_medium_cells.py` replays the probe on every record.
`tests/test_installer_probe_label.py` holds the label reader to the result
of the layer scan.
`scripts/lib/installer_medium.py` validates the table.

### Explicit rows

`[[installer_medium.cells]]` can declare `filesystem`, `bootloader` and
`backend` with a `reason`. Use it for an image that the scan cannot read:
`tromso:kde` and `brussels:xfce` are BuildStream images and have no matrix
flavor. A declared bootloader or backend that contradicts the evidence fails
validation. A declared ext4 can replace a measured btrfs. The checklist in
[`docs/retire-path.md`](docs/retire-path.md#onboarding-checklist) says what a
new BuildStream image needs.

### Bootloader target

`evidence/bootloader-target.json` records, for each base, if the distribution
publishes a signed systemd-boot and who signs it (tunaOS#4955). The resolver
reports a target for each variant next to the current bootloader. No cell
changes its bootloader from that record.

### Secure Boot

Each supported cell has a `secure_boot` mode (tunaOS#4955):

- `distro-chain`: the distribution signs what the medium boots. Every GRUB
  cell has it. A systemd-boot cell has it only when the shim of the base
  accepts the signed systemd-boot (`shim_accepts` is `yes`).
- `tunaos-key`: the CI of tunaOS signs systemd-boot. `secure_boot_enroll` says how
  the medium enrolls the key: `if-safe` (default), `manual`, `off` or `force`.
  A `tunaos-key` cell always boots systemd-boot.

`secure_boot_vendor_sha256` pins the vendor certificate of a `distro-chain`
cell. `[[installer_medium.cells]]` can declare all four fields with a
`secure_boot_reason`; the validator applies the same rules. When
`secure-boot/bases.toml` (tunaOS#4958) is in the tree, the resolver takes
`shim_accepts` and the pins from it.

### Wahoo

Wahoo is Fedora ELN. Its `os-release` has `rhel` in `ID_LIKE`, so the
resolver puts it with the EL bases and gives it xfs. That is the intended
result: ELN is the EL base of the next release, not a Fedora desktop base.
`tests/test_installer_medium_config.py` holds the row to xfs.

### Redfin and the BuildStream images

Redfin (RHEL 10) is not in `tunaos.toml`, so it has no row. It is an EL10
base, so its filesystem is xfs. No scan has read its bootloader and backend:
the image is local-build only. See [`docs/retire-path.md`](docs/retire-path.md)
for that and for the BuildStream repositories.

## Build flow

```bash
installer-medium/build-medium.sh CELL OUT.ISO [--dry-run]
```

Steps in order:

1. `build-live-image.sh`: podman builds `Containerfile.live` FROM the cell
   ref. The live layer carries skip drop-ins, the live setup, and the
   dracut config. It never alters the deployed image behavior: each unit
   keys off `tunaos.live`. A payload stage also builds `fishermand` from
   `fisherman_ref` (`daemon/build-fishermand.sh`) and runs
   `frontends/install-frontend.sh` for the cell's desktop. The layer ships
   the four `fishermand-*.socket` units, `fishermand.service`, the polkit
   policy and rules, and the autostart entry. This step runs before repart
   copies the partitions, so every later step carries the daemon and frontend.
   `verify-cell-layout.sh` then runs the probe inside that image.
2. `build-to-disk.sh`: `bootc install to-disk` writes the live layer image
   to a blank disk with the cell backend and bootloader. The disk is sized
   from the image (x1.25, plus `MEDIUM_FLATPAK_RESERVE_MB` and
   `MEDIUM_BOOT_RESERVE_MB`); `MEDIUM_RAW_SIZE` overrides.
3. `add-live-entry.sh`: writes the live boot entry. GRUB cells get a BLS
   entry, and copies of the kernel and initrd on the ESP. Systemd-boot cells get a
   Type #1 entry plus the live-only initrd (Dakota pattern).
4. `sysext/build-sysext.sh` + `place-sysext.sh`: the sysext
   with the pinned systemd goes into `/var/lib/extensions` on the medium.
   On an ostree or composefs medium that is the `var` directory of the
   deployment, not `var` of the mounted root (`medium-paths.sh`).
5. `repart/build-hybrid.sh`: `systemd-repart --el-torito=yes` copies each
   partition with `CopyBlocks=` into the hybrid file. One file boots as CD
   and as dd-written USB.
6. `flatpak/bake-flatpaks.sh`: installs and deploys the fixed set from
   `[flatpak_preinstall]` into `/var/lib/flatpak`, then
   `scripts/check-flatpak-medium.py --store` reads the deployed store
   (`flatpak list`) and proves it equals the generated policy.
7. `publish/chunk-publish.py`: chunks, compresses, and writes the OCI
   layout that `tacklebox write-medium` reads.

`--dry-run` prints each step and touches nothing. The test suite drives it
without root.

## The daemon

`fisherman_ref` pins fisherman#520, the real `fishermand` executor. The
daemon knows the live entry `medium-live` and the `tunaos.live` kernel
argument. On the installed copy it removes the medium-only sysext and
`EFI/tunaos-live`. It supports encrypted installs only.

`fisherman_repo` is `tuna-os/fisherman` (archived 2026-11-26) or `tuna-os/installer`,
where fisherman moved with its history (installer#495). The Go module is at
`fisherman/` in the first and `fisherman/fisherman/` in the second;
`daemon/fisherman-module-dir.sh` finds it in either, so moving the pin is a
`tunaos.toml` change only.

## Secure Boot

`secure-boot/stage-medium.sh MODE ROOT ESP` runs after the live entry exists.
`MODE` is `distro-chain` or `tunaos-key`; CI sets `MEDIUM_SECURE_BOOT` until
each cell has a `secure_boot` field. `distro-chain` verifies the distro files
and stages nothing. `tunaos-key` stages shim, MokManager, the certificate and
the key bundle. Only CI signs (`secure-boot/ci-sign.sh`). See
`docs/SECURE-BOOT.md` for the facts per base, the flows and the threat notes.

## CD boot support

Linux does not scan `sr` devices for partitions. The `90medium-sr0` dracut
module starts a service for each drive. The service attaches a disc that has
a GPT as a read-only loop device. PARTUUID paths then resolve on both boots.
A GRUB cell also needs `repart/iso-grub-stub.py`: the signed GRUB looks for
its configuration in the ISO 9660 file system of the disc.

An image with no dracut keeps its own initramfs, so the module is not in it.
A Type #1 live entry of such a cell (Brussels, Tromsø) carries the same
service, rule and script in `live.initrd`, which `add-live-entry.sh` appends
to the image's initrd. The script needs only `losetup` and `udevadm`: the
initrd of a GNOME OS image has no `dd`. A UKI cell with no dracut has no
initrd to append to, and its CD boot has no fix yet.

## Hooks for #4908 and #4909

- `hooks/initrd-90medium-install/`: initrd module slot for the seed,
  migrate, copy, and soft-reboot payload.
- `hooks/medium-install-post`, `medium-install-post@.service`: target-disk
  finish step that gnome-setup starts.
- `docs/btrfs-seed-migrate-hook.md`, `docs/el10-soft-reboot-hook.md`:
  the contracts that each issue makes.

## Boundaries

- `.github/workflows/` belongs to the CI session.
- `installer-medium/frontends/{kde,cosmic,niri,xfce}/` belong to the native-frontend session. See `frontends/README.md` for the contract.
- Never post the vendored patch upstream; systemd#44968 carries it.
