# Retire path: old installer adapters and their replacements

ADR 0018 retires the ISO, fisherman and bootc-installer path only after the
suite of the image installer meets its exit criteria. This page is the
record for that step. It deletes nothing. Each row names an old part, the part of
`installer-medium/` that replaces it, and what the replacement does not do
yet. [`cells.md`](cells.md) lists the status of every cell.

## Live-session adapters

`live-iso/common/src/customize-live.sh` sources one adapter for each desktop.
The medium replaces each adapter with a frontend directory and the shared
`medium-live-setup`.

| Old adapter | What it does | Replacement | Still missing |
|---|---|---|---|
| `desktop-gnome.sh` | GDM autologin in `/etc/gdm` and `/etc/gdm3`, dock favorites, no suspend, installer in front of the overview | `frontends/gnome/install.sh` (gnome-setup, overview extension, power settings) and `medium-live-setup` (GDM autologin, both paths) | Dock favorites: not ported, the live session shows only the installer. |
| `desktop-gnome.sh` on `tuna` flavors | The same adapter: Tuna Desktop runs gnome-shell behind GDM | `frontends/tuna/install.sh`, which runs the GNOME frontend under the name `tuna` | No Tuna cell has run the medium end to end. The portal check of the apt variants is blocked (`[tuna_rollout]`). |
| `desktop-pantheon.sh` | LightDM autologin, X11 session first | `frontends/pantheon/install.sh` (gnome-setup and the LightDM hook) | `gurnard:pantheon` has not run the medium end to end. |
| `desktop-kde.sh` | SDDM autologin to Plasma, no screen lock, suspend targets masked | `frontends/kde/install.sh` and `medium-live-setup` (SDDM autologin) | Screen lock and suspend masks. |
| `desktop-cosmic.sh` | greetd autologin to cosmic-session, `cosmic-greeter.service` masked, no lock, no suspend | `frontends/cosmic/install.sh` | greetd autologin: `medium-live-setup` writes GDM and SDDM only. The greeter mask. |
| `desktop-niri.sh` | greetd autologin (dms-greeter or `niri-session`), no lock, no suspend | `frontends/niri/install.sh` (`spawn-at-startup` line) | greetd autologin. |
| `desktop-xfce.sh` | greetd autologin on the Wayland session, LightDM or GDM on X11 bases, installer autostart, no suspend | `frontends/xfce/install.sh` | greetd and LightDM autologin. |

Measured in the tree, not on a boot: no file below `installer-medium/` writes
a greetd or LightDM autologin for `cosmic`, `niri` or `xfce`, and
`medium-live-setup` writes GDM and SDDM only. The old adapters needed that
autologin to reach the session. No medium run has shown what those cells
reach without it; the promoted `bonito` cells are the first to tell.

## Installer frontends

| Old frontend | Old backend | Replacement | Still missing |
|---|---|---|---|
| GNOME: `org.bootcinstaller.Installer` (upstream bootc-installer) | Its own disk backend | gnome-setup from `frontends/gnome-setup/` (pinned commit and patch series), for `gnome`, `tuna` and `pantheon` | The patch series is not upstream (`frontends/gnome-setup/upstream-drafts/`). |
| KDE: `org.tunaos.InstallerKde` | fisherman through `recipe.json` | The same application, pinned by digest, with `TUNA_INSTALLER_BACKEND=daemon` | An end-to-end run with the daemon backend. The pin holds the client since bootc-installer `25452dd`. |
| COSMIC: `org.tunaos.InstallerCosmic` | fisherman through `recipe.json` | The same application with `TUNA_USE_FISHERMAND=1` | The same end-to-end run. No tested AT-SPI tree: the run uses OCR. |
| Niri: `org.tunaos.InstallerNiri` | fisherman through `recipe.json` | The same application with `TUNA_INSTALLER_BACKEND=daemon` | The same end-to-end run. OCR input. |
| XFCE: `org.tunaos.InstallerXfce` | fisherman through `recipe.json` | The same application with `BOOTC_INSTALLER_BACKEND=daemon` | The same end-to-end run. |

## Recipe and backend

| Old part | Replacement | Still missing |
|---|---|---|
| `installer-recipe-backend.sh` called at ISO build time to fill `recipe.json` (`bootloader`, `composeFsBackend`, `filesystem`) | The same script, run by `evidence/scan-images.py` on the published image and by `verify-cell-layout.sh` at build time. `scripts/lib/installer_medium.py` resolves each cell from the result. | Keep the script when `live-iso/` goes: move it to `installer-medium/`. |
| `recipe_payload.py` and the fisherman `recipe.json` | `fishermand` (fisherman#520) behind four Varlink sockets, started by `fishermand.service` | EL10 soft reboot (#4908, #4909). Unencrypted installs: the daemon supports encrypted installs only. |
| `fetch-installer-bundle.sh` (Flatpak bundle from a release) | `frontends/*/pin.env` (OCI digest) | Nothing. |
| `/usr/local/bin/fisherman` and its polkit rule in the live root | `daemon/build-fishermand.sh` and `live/usr/share/polkit-1/` | Nothing. |

## What each variant still needs

The generated table gives the status of each cell. This list gives the
reason behind each group that is not `promoted`.

| Variants | State | Needed before promotion |
|---|---|---|
| `yellowfin`, `albacore`, `skipjack` (EL10) | Supported on xfs with GRUB and ostree | The EL10 handoff (#4908, #4909). One green end-to-end run for each desktop. |
| Redfin (RHEL 10) | No row: the variant is not in `tunaos.toml` and its image is local-build only | A matrix entry, then a local `scan-images.py` run or a declared row. xfs by policy. |
| `hummingbird` | The probe keeps xfs: `ID_LIKE` has `rhel` | Its own btrfs check (#4906). The image ships no desktop packages of its own. |
| `wahoo` (Fedora ELN) | See `cells.md`: the measured `os-release` decides the filesystem | An owner decision if ELN counts as an EL base. |
| `bonito`, `bonito-rawhide` | Supported; five `bonito` cells promoted | End-to-end runs for the hardware flavors and for `tuna`. |
| `marlin`, `sailfin`, `guppy` | See `cells.md` | A green end-to-end run. `medium-live-setup` uses `useradd`, `passwd` and a `wheel` group; nobody checked them on these bases. |
| `grouper`, `gurnard`, `stingray`, `flounder`, `flounder-sid` (apt) | See `cells.md` | A green end-to-end run. `cells.md` names the flavors with no published image and the flavors that are not built. |
| arm64-only flavors (`gnome-asahi`, `gnome-x13s`) | Evidence read from the arm64 image | An arm64 lane: the workflow boots x86_64 QEMU only, and `matrix.py --cell` refuses these cells. |

## BuildStream variants (other repositories)

Tromsø, Brussels (the repository was `xfce-linux`) and Athens build in their
own repositories with BuildStream. They are `[[sibling_images]]` in
`tunaos.toml`, not matrix variants, so the resolver has no rule for them.
`tunaos.toml` declares the cells `tromso:kde` and `brussels:xfce`;
`xfce-linux:xfce` is a deprecated alias. A sibling publishes `latest` and
`stable`, not one tag per desktop: `installer_tag` in the sibling record
names the tag that the medium reads.

| Repository | Cell | State | What the repository must provide |
|---|---|---|---|
| tuna-os/tromso | `tromso:kde` (ext4, systemd-boot, composefs, `tunaos-key`) | Image `sha256:2b89f634081f` read from `ghcr.io/tuna-os/tromso:latest` on 2026-11-26: kernel 6.19.11, no signed systemd-boot. The build on `main` fails (run 45899365958, step `build_core`). No VM run exists for this cell. | A green build on `main` that publishes a new image. A kernel at 7.4-rc2 or later before the cell can use btrfs. The tunaOS signature on systemd-boot and the kernel, and the files of `/usr/lib/tunaos/secure-boot/` (tuna-os/tromso#516). |
| tuna-os/brussels | `brussels:xfce` (ext4, systemd-boot, composefs, `tunaos-key`) | Image `sha256:a2668a1c2e39` read from `ghcr.io/tuna-os/brussels:latest` on 2026-11-26: kernel 7.0.11, `systemd-bootx64.efi.signed` present. The build on `main` is green (tuna-os/brussels run 45817609397). `ghcr.io/tuna-os/xfce-linux` is an alias of the same digest. No VM run exists for this cell. | The live session uses GDM, which the autologin hook of the medium knows. No run has shown that hook with this image yet. |
| tuna-os/athens | `athens:pantheon` (not declared) | Local-only today. | A public image. Then a declared row; the `pantheon` frontend applies. |

Each of those repositories can run
`live-iso/common/src/installer-recipe-backend.sh` on its image with
`TUNAOS_INSTALLER_ALLOW_BTRFS=1` to get the three values for its row.

A sibling repository does not copy the build scripts or the harness. Its
workflow calls `.github/workflows/image-installer.yml` of this repository
with `workflow_call`, at a pinned commit. The call names the cell, the same
commit as `tunaos_ref`, and the registry path for the installer image.

The baseline for stage 6 is the digest of the `installer_tag` image. Stage 7
needs a `candidate` digest from the caller; with none, it stays a marker.

The cell has `secure_boot = "tunaos-key"`. The step that stages shim and the
key bundle on the medium is in tuna-os/tunaOS#4958. The harness has no Secure
Boot firmware yet. So a run today proves the cell with Secure Boot off only.

### Onboarding checklist

A sibling is complete when all eight lines are true. Each
line needs evidence: a file in this repository, or a run id. A line without
evidence stays open, and the table above says so.

1. **Record.** `[[sibling_images]]` in `tunaos.toml` has the fields `id`,
   `emoji`, `description`, `repo`, `desktops`, `mark` and `availability`. The
   repository is `tuna-os/<id>`. A published image also has `image`
   (`ghcr.io/tuna-os/<id>`), `workflow` and `installer_tag`. An unpublished
   sibling has `target` and none of those three.
2. **README.** The sibling has one row in "Choose your image" and one row in
   the BuildStream family table. Both rows use the name and the mark of the
   record. The Availability text says what is true. An unpublished sibling
   says that it has no public image. Never write a green mark without a run
   id. The generator fills the build column from the latest conclusive run
   on `main`.
3. **Cell.** `[[installer_medium.cells]]` declares `<id>:<desktop>` with
   `filesystem`, `bootloader`, `backend`, `reason` and `secure_boot`. Run
   `scan-images.py --cell <id>:<desktop>` on the published image, so that
   `evidence/images.json` holds the digest that the layout comes from.
   Run `gen-installer-medium-cells.py` after that.
4. **Secure Boot.** The CI of tunaOS signs systemd-boot with the `tunaos-key`.
   The image carries the files of `/usr/lib/tunaos/secure-boot/`.
   `secure-boot/image/verify-image.sh` passes on the published digest. Record
   the run id of the run that signed it.
5. **Public image.** An anonymous pull of the `installer_tag` image works,
   and the digest has a keyless cosign signature. Only the owner of the
   organization sets the visibility of a package.
6. **Build.** The workflow of the record has a green run on `main`. The README
   row links to it.
7. **Proof.** One dispatch of `image-installer.yml` for the cell, with
   `publish=false`, passes all seven stages from USB and from CD. SELinux
   reports `Enforcing`. A person has opened the pictures of each stage. The
   run id is in the table above. Only then does the cell get
   `promoted = true` and enter the nightly.
8. **Names.** Every file uses the current name. The old name appears only as
   a declared alias. `tests/test_sibling_images_are_reported.py` passes.

### The same standard for every sibling

A sibling meets the same gates as a matrix desktop. The standard for
desktops is in `DESKTOP-STANDARD.md` of the installer work. For a sibling, a
gate with no bootc mechanism has an equivalent. A skipped gate is never
silent: the table below says `unproven` or names the issue.

| Gate | Brussels, Tromsø | Athens, Ubuntu Core Desktop |
|---|---|---|
| Stages 1 to 5 (live boot, pages, install, recovery key, first boot) | The same stages, USB and CD, on `image-installer.yml` with the cell `<id>:<desktop>`. A person reads the pictures. | Athens: the same, once it has a cell. Ubuntu Core Desktop: a disk image has no installer medium, so its analogue is the first boot of the built image (open: #5130). |
| Stage 6 | `bootc status` names the booted digest. | The update status of the image, such as `updatectl` or `snap changes`. Record it. |
| Stage 7 | Switch to a second digest, then roll back. With one digest, write `todo: needs 2 digests` (#5128). | The real A/B or `snap revert` rollback of the image, or the same `todo`. |
| Signature | An anonymous pull, then `cosign verify` against the workflow identity (#5125). | Athens: the same once published. Ubuntu Core Desktop: a scheme for disk images (#5130). |
| Public image | Anonymous pull of `installer_tag` works. Only the owner sets visibility. | Athens: none today (#5129). |
| Security module | Stage 6 records `Enforcing` (#5126). | Stage 6 records the documented module, such as AppArmor (#5126). |
| Boot gate | The sibling CI boots the image before it publishes `latest` (#5087). | Athens: the same (#5129). Ubuntu Core Desktop: the CI gate exists (dispatch only). |
| Screen reader | The image ships one and the setting reaches the installed system (#5127). | The same (#5127). |

### Status of each sibling cell

`unproven` means that no run on a current image shows the gate. Run ids are
runs of tuna-os/tunaOS, unless the cell says otherwise.

| Cell | Published | Signed | Boot gate | Installer cell | Stages 1 to 7, USB and CD | Owner | Next gate |
|---|---|---|---|---|---|---|---|
| `tromso:kde` | Yes, but the old image `sha256:2b89f634081f` | Unproven: that image has no signed loader | No (#5087) | Declared, promoted | Unproven: no run | SigningBrussels, TromsoOgc | A green signed build on `main` (run 45899365958 fails), then one dispatch |
| `brussels:xfce` | Yes, public `sha256:a2668a1c2e39` | Yes: run 45817609397 signed it, and cosign verify passed once (#5125) | No (#5087) | Declared, not promoted | USB: stages 1 and 2 pass, stage 3 fails (pod run 45931350733). Hosted run 45905755933: stage 1 fails on USB and CD. Stages 4 to 7: unproven | XfceDesktop | The live session must take the display, then stage 3 |
| `athens:pantheon` | No | No | No (#5129) | Not declared | Unproven: no run | PantheonOnboard (tuna-os/athens#12) | An image build and a boot gate (#5129) |
| `ubuntu-core-desktop` | No | No | Yes in CI, dispatch only (runs 45935173447, 45935184347) | None: a disk image | Unproven | UcdBuild | Owner decision, signing, installer analogue (#5130) |
