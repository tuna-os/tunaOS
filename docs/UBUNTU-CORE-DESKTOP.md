# Ubuntu Core Desktop as a TunaOS variant

Status: investigation with one boot test. Read on 2026-11-26.
Issue: [#4930](https://github.com/tuna-os/tunaOS/issues/4930).
Source: [canonical/ubuntu-core-desktop](https://github.com/canonical/ubuntu-core-desktop)
at commit `7a1e8b2b`.

## Answer

- Ubuntu Core Desktop is not a base for the TunaOS OCI pipeline.
- It is a separate kind of system, and it works today. It can be a variant of
  its own, built and tested with the practices in this document.

## What was tested

The `gnome-latest` release of Canonical's repository is a raw disk image.

| Item | Value |
| :--- | :--- |
| Download | `ubuntu-core-desktop-gnome.img.zst`, 1994 MiB |
| SHA-256 | `a1cb05479dfc55c91293314b0024149423f45dfc46f8c7cf7f169e7dd0d4af7c`, checked against the published `SHA256SUMS` |
| Built | 2026-11-26 18:38 UTC, commit `7a1e8b2b`, snap versions in `manifest.txt` |
| Test machine | QEMU 8.2.2 with KVM, OVMF, 4 vCPU, 4 GiB, no network forward |
| Result | The image reached the GNOME first-boot wizard ("Welcome to Ubuntu", 11 steps) in about 3 minutes |
| Kernel | `7.0.0-44-generic`; the log shows the Canonical Secure Boot signing key |

Evidence: a screenshot of the wizard and the serial log, kept in the
program evidence folder (`evidence/ucd-gnome-latest`).
The test did not run the wizard, did not run `snap refresh`, and did not
run a rollback.

## Why it is not an OCI base

| | TunaOS (`Containerfile.ubuntu`) | Ubuntu Core Desktop |
| :--- | :--- | :--- |
| Unit of build | OCI image, `FROM ubuntu:<release>` | Signed model assertion plus snaps |
| Packages | `apt` | Snaps: base, gadget, kernel, `snapd`, session |
| Image tool | `podman build`, then `bootc` | `ubuntu-image` writes `pc.img` |
| Updates | `bootc upgrade` from a registry | `snapd` refreshes from the Snap Store |
| Boot chain | systemd-boot and composefs | Ubuntu Core initramfs and its own run mode |

- Ubuntu Core has no OCI base image, so a `FROM` line has nothing to name.
- Our variants install deb packages. On Core every payload is a snap.
- Both systems own `/usr`, the boot chain and the update path. A hybrid would
  make them fight over each.

## What changed since the first investigation

The first version of this document (PR #4999) said that the Canonical build
chain does not work. That is wrong today.

- The workflow `build-image.yaml` assembles an image from the release snaps of
  thirteen repositories. It then builds a second, throwaway image with a gate
  account, boots it, and fails the run unless `gnome-shell` runs. Only then
  does it publish.
- Canonical publishes `gnome-latest`, `kde-latest` and `gnome-arm64-latest`
  releases, dated 20261126.
- The image has no preset user or password. The first-boot wizard makes the
  account.
- The model has `grade: dangerous`. A local `test` key signs it, and the
  public account key is in `ci/`. A `dangerous` image does not need a Canonical
  brand key.

Limits that remain, from the repository's own notes:

- The images use unasserted, locally built snaps. They never get a Snap Store
  refresh, so they get no security updates.
- The base snap `core26-desktop` is deliberately not store-published.
- A `signed` grade model needs every snap in the Snap Store and a brand account
  that signs the model. Canonical's infrastructure team signs the release model.
- There is no installer. The user writes the image with `dd`.
  The write copies all the padding of the image (issue `20261111`).
- Refresh and rollback of the snap paths in the base were never tested
  (issue `20261108`).

## Practices checked against TunaOS

The first version of this section did not check each practice against this
repository. This version does. Checked on 2026-11-27.

| Practice | TunaOS today | Verdict |
| :--- | :--- | :--- |
| Boot a throwaway image before publish | Every bootc cell boots in the Gate job of `reusable-build-image.yml` (`scripts/corral-boot-gate.sh`) before it is promoted. The BuildStream siblings do not: Brussels and Tromsø publish `latest` without a boot. | Gap for the siblings. The first Brussels boot test found four faults (session, network, SSH key, CD root). |
| Gate the installer medium every night | `image-installer.yml` has no schedule (TODO #4910). | Gap. Enable the nightly after the cells are green. |
| Two boots for a slow first boot | The corral gate and the e2e harness wait with long timeouts. | No change. |
| Check the real mode, not the command line | The harness reads the root device of the installed system (`INSTALLED_PROBE`). | Done. |
| Disposable images: `cache=unsafe`, four vCPUs | The harness sets only `-m` and `-smp`. | Open. Measure before the change. |
| PNG screendumps | The harness writes PPM and converts. QEMU 10.2.1 shears PPM when the width is not divisible by 4. | Open. Safe at 1280 pixels, but the runners move to Ubuntu 26.04 and QEMU 10.2. |
| One manifest with each release | `docs/matrix-provenance.json` and the SBOM attestation. | Done. |
| Land fixes in git | `AGENTS.md` has the rule. | Done. |

Ideas from their issue list, not yet in TunaOS:

- **A block map for USB writes.** Their install wrote 21.5 GB, and only 4.8 GB
  held data (issue `20261111`). Our medium is a hybrid disk image
  that a person writes to a USB drive. A `.bmap` file, made in CI, lets a tool
  skip the empty blocks.
- **A network install.** Their image carries snaps that the first update
  replaces (issue `20261116`). Our medium carries a full image for an offline
  install, and `bootc upgrade` then fetches a newer one. A smaller medium that
  pulls the image at install time is a choice to make.
- **The keyboard layout at the unlock prompt.** An unusual layout can lock a
  person out of an encrypted disk (issue `20260930`). A TunaOS install
  without a TPM asks for the passphrase at every boot. Check that the layout
  from the installer reaches the initramfs prompt.

Already done here: one script with per-desktop functions
(`manifests/desktops/*.yaml`), and the display manager of each desktop
(`display_manager` in every manifest).

## Variant plan

Stage 1 lists the upstream images in the TunaOS image matrix as a disk-image
variant. The record points to the Canonical release and reports its latest
build. We do not build the image.

Stage 2 builds the image in TunaOS CI. It reuses the Canonical release snaps,
the `build.sh` flow and the boot gate. It publishes nothing. See
[Stage 2: the CI build](#stage-2-the-ci-build).

Stage 3 would add the TunaOS brand and the TunaOS installer. That needs a model
and snaps that we control. It also needs a decision on the brand account in
the Snap Store.

Revisit the OCI question only if Canonical ships an OCI form of
`core26-desktop`.

## Stage 2: the CI build

Status: built and boot-gated for GNOME and KDE on 2026-11-27. The workflow
publishes nothing.

The workflow is `.github/workflows/ubuntu-core-desktop-image.yml`. A person
starts it from the Actions tab or with `gh workflow run`. It has no schedule
and no other trigger.

Inputs:

- `desktop`: `gnome` or `kde`.
- `upstream_ref`: a full 40-character commit of `canonical/ubuntu-core-desktop`.
  The default is `7a1e8b2b41fab1dcb957bf4e670dbae372421aa8`.
- `gate`: `true` by default. With `false` the run skips the boot gate.

Steps:

1. Check out `canonical/ubuntu-core-desktop` at `upstream_ref`.
2. Download the `desktop-26-latest` release snaps, as upstream does.
3. Build a throwaway gate image with a `gate` account.
4. Boot it under QEMU with KVM twice. Hold one SSH session open. The cold boot
   waits for `snapd.seeded`. The warm boot waits for the session process:
   `gnome-shell` or `plasmashell`.
5. Take screenshots over QMP as PNG.
6. Build the image that is kept, with no baked credentials.

Outputs:

- Artifact `ubuntu-core-desktop-<desktop>-image`: the `.img.zst` file,
  `SHA256SUMS` and `manifest.txt`. Actions keeps it for one day. The image is
  about 2 GB and the repository has 0.5 GB of Actions storage.
- Artifact `ubuntu-core-desktop-<desktop>-evidence`: the screenshots, the
  gate report, the serial logs, `manifest.txt` and `SHA256SUMS`. Actions keeps
  it for 14 days. It exists when the gate fails.

`manifest.txt` holds the upstream commit, the workflow commit, the run URL and
the version and SHA-256 of every snap.

The workflow has `contents: read`. It has no release, registry push, Snap
Store upload or secret. `tests/test_ubuntu_core_desktop_image_workflow.py`
fails when a change adds one.

What this does not do:

- It does not test the first-boot wizard of the kept image. The gate image has
  an account and skips the wizard.
- It does not test `snap refresh` or rollback.
- It does not make the image safe to ship. The snaps have no Snap Store
  assertions. A test key signs the model.
- It does not run on our ARC runners. They have no `snapd` and no KVM, so the
  job uses GitHub-hosted `ubuntu-26.04`.
- It does not prove that the first-boot failure below is gone. Five runs are
  too few.

### What the runs showed

Date: 2026-11-27. All runs used `7a1e8b2b` and the `desktop-26-latest` snaps
that were on the releases that day. The program evidence folder
`evidence/ucd-ci-build` keeps the screenshots and logs of every run.

| Run | Desktop | Result |
| :--- | :--- | :--- |
| [45928752151](https://github.com/tuna-os/tunaOS/actions/runs/45928752151) | GNOME | Gate failed. `snap change 1` ("Initialize system state") ended in Error 3 minutes into the cold boot. The VM then stopped answering SSH. The run did not record why. |
| [45932296713](https://github.com/tuna-os/tunaOS/actions/runs/45932296713) | GNOME | Green. Same code, plus diagnostics. The gate took 4.7 minutes. |
| [45934043254](https://github.com/tuna-os/tunaOS/actions/runs/45934043254) | KDE | Gate failed. The `snapd` journal says: `Start snap "plasma-desktop-session" (x1) services failed: some user services failed to start`. |
| [45935173447](https://github.com/tuna-os/tunaOS/actions/runs/45935173447) | GNOME | Green, with the fix below. |
| [45935184347](https://github.com/tuna-os/tunaOS/actions/runs/45935184347) | KDE | Green, with the fix below. |

The cause is a theory. The gate polls over SSH every 10 seconds. Each poll
opened and closed the only login session of the `gate` user. Then
`systemd --user` for that user started and stopped while `snapd` ran its first
boot. The gate now holds one SSH session open for the whole boot.

Before the change, GNOME passed 1 of 2 runs and KDE passed 0 of 1. After it,
both passed. That is a correlation, not a proof. Upstream's gate polls the same
way. This work did not test if upstream has the same risk.

What the green runs proved:

- The cold boot reaches `snapd.seeded`. The warm boot starts `gnome-shell` or
  `plasmashell`, with a session on `seat0` and no failed `systemd` unit.
- The screenshots show a GNOME desktop (Ubuntu dock, "Resolute Raccoon"
  wallpaper) and a Plasma desktop. The KDE picture at 45 seconds shows the
  Plasma splash. The picture at 75 seconds shows the desktop.
- The GNOME artifact of run 45932296713 passed `sha256sum -c` and `zstd -t`.
  It expands to 21.5 GB.
- The artifacts are 2.1 GB (GNOME) and 2.7 GB (KDE).

What they did not prove:

- The cold-boot screenshot (`cold-seeded.png`) shows the stale text console,
  not a desktop. Use `warm-session-*.png`.
- The gate passes when the session process exists. A person reads the pictures
  to see that the desktop painted.
- The kept image did not boot in these runs. Only the gate image did.

A new `workflow_dispatch` workflow cannot run until it exists on `main`.
`gh workflow run --ref <branch>` returns HTTP 404 before that. The first run
therefore came after the workflow merged.

## Pantheon on Ubuntu Core Desktop

Status: investigation with a build probe. Read on 2026-11-27.
Source: [canonical/ubuntu-core-desktop](https://github.com/canonical/ubuntu-core-desktop)
at commit `df928ff`, and its component repositories on branch `desktop/26`.
The owner asked: "Could we put Pantheon on Ubuntu Core Desktop?"

### Verdict

- Yes, it is possible. No law of the platform forbids it. Both existing
  sessions are ordinary snaps, and the build tools take a list of them.
- It is not cheap. A Pantheon session is a new set of snaps, a new model and
  a new block of image glue. It is about the size of the KDE work, with less
  prior art.
- Nobody has built it. The upstream tools know two desktops: `gnome` and `kde`.
- Nothing here boots. The probe below proves that the shell compiles and that
  `snapcraft` can pack a `core26` snap. It does not prove a session.
- Upstream would need to accept a third desktop, or TunaOS carries a patch on
  top of a pinned checkout. The second path needs no one's permission.

### How the GNOME and KDE sessions are packaged

All facts come from the repositories at the commit above.

| Item | GNOME | KDE |
| :--- | :--- | :--- |
| Model | `ubuntu-core-desktop-26-amd64-dangerous.json` | `ubuntu-core-desktop-kde-26-amd64-dangerous.json` |
| Session snap | `ubuntu-desktop-session`, base `core26`, 1997 lines of `snapcraft.yaml`, 72 apps | `plasma-desktop-session`, base `core26-desktop`, 934 lines, 19 apps |
| Runtime snaps | `gnome-desktop-runtime` (content snap with mutter, GNOME Shell, `gsd`, GDM) | `kf6-core26` (Qt 6, KDE Frameworks) and `plasma-core26-desktop` (Plasma) |
| Helper snaps | `accountsservice`, `provd`, `fprintd`, `bolt`, `geoclue`, `ubuntu-desktop-a11y`, `pipewire` | none of those; the model lists `udisks2`, `avahi`, `bluez` |
| Display manager | GDM, part of the `core26-desktop` base (variant `desktop`) | SDDM, shipped inside the session snap and wired into the image by `kde_sddm_integration` in `build.sh` |
| Session entry | a `wayland-sessions` file that starts `core-desktop-session-wrapper.sh` | the same wrapper, other arguments: `plasma-desktop-session KDE` |
| Plug wiring | `gnome_gadget_connections` in `build.sh`, written into `gadget.yaml` | `kde_gadget_connections`, a shorter list |
| First boot | `ubuntu-desktop-init`, started by GDM initial setup | `plasma-setup`, started by a unit that `build.sh` installs |
| Fork of `snapd` | interfaces such as `systemd-user-control`, `desktop-launch`, `login-session-*`, `gdm-session-control` | at least five more commits for KDE (`kde-kauth`, `pam-unix-chkpwd`, KWin session environment, XDG directories) |
| Source repositories | `canonical/*` | `chris-bainbridge/*` forks of KDE Neon Core |
| Build | each repository builds its snap in CI and updates a rolling `desktop-26-latest` release; the image workflow downloads them | the same |

How the tools choose a desktop:

- `build-snaps.sh` reads a table with one row per component: name, repository,
  release tag, asset, local name, `gnome`, `kde` or `both`, branch.
- `build.sh` has a `case` on `--desktop` for the model and the wrapper
  arguments. It calls one function for the gadget. For KDE it calls a second
  function for the display manager.
- The image is one `ubuntu-image` run on a signed `grade: dangerous` model.
  Local snaps replace the store snaps that the model names.

Cost evidence from the git history of `canonical/ubuntu-core-desktop`:

| Date | Event |
| :--- | :--- |
| 2026-10-06 | The KDE model and the SDDM integration land. |
| 2026-10-13 | CI builds and publishes a KDE image. |
| 2026-10-16 to 2026-11-07 | The first-boot wizard, PAM services, `kauth` and XKB fixes land. |
| 2026-11-27 | KDE still has open AppArmor issues and no `arm64` image. |

The KDE snaps were not new work. They started as `core24` packages from the Neon project of KDE. Pantheon has no such base. This is an estimate, not a measure:
expect more than the first week.

### What Pantheon needs

Facts about Pantheon come from the `elementary/*` repositories and from the
Athens recipe (`tuna-os/athens`), which already builds Pantheon on a GNOME OS
runtime.

| Piece | What it does | Where it comes from on core26 |
| :--- | :--- | :--- |
| `gala` | Compositor and window manager, built on libmutter | Source. Release 8.6.2 builds against Ubuntu 26.04 (probe). The elementary PPA has a `resolute` package of `gala`, but not of the rest. |
| `wingpanel` and indicators | Top panel | Source. Release 8.0.4 does not configure against mutter 50. `main` does not compile with the `gtk4` Vala bindings of 26.04 (probe). |
| `io.elementary.dock` | Dock | Source. Release 8.3.3 builds (probe). |
| `io.elementary.settings` (Switchboard) and plugs | System settings | Source. Release 8.0.3 builds (probe). The plugs are about 20 more repositories. |
| `io.elementary.settings-daemon` | Pantheon's own settings daemon | Source. Release 8.5.0 builds (probe). |
| `io.elementary.greeter` | Login screen for LightDM | Source. `main` needs the LightDM Vala binding, which 26.04 does not ship (probe). Athens builds LightDM from source. |
| `granite` 6, 7 | Toolkit. Version 6 is GTK 3 and `gala` and the greeter still need it. | Version 7 is in the Ubuntu archive (7.8.0). Version 6 is source only (6.2.0 builds, probe). |
| `pantheon-wayland` | Wayland helper library for the shell | Source. Release 1.1.0 builds (probe). The PPA has a `resolute` package. |
| Session files | `gala@wayland.service`, `gala.target`, `io.elementary.desktop.wm.shell`, session settings | In the `gala` and `session-settings` repositories. They are `systemd` user units that start the GNOME Settings Daemon units too. |
| Portals, polkit agent, notifications | Shell integration | `io.elementary.portals`, `pantheon-agent-polkit`, `io.elementary.notifications`. All build (probe). |

Library versions in the Ubuntu 26.04 (`resolute`) archive, from the Launchpad API:

| Package | Version |
| :--- | :--- |
| `mutter` | 50.1 |
| `gtk4` | 4.22.4 |
| `libadwaita-1` | 1.9.1 |
| `vala` | 0.56.18 |
| `granite-7` | 7.8.0 |
| `gnome-settings-daemon` | 50.0 |
| `lightdm` | 1.32.0 |

`gala` main accepts mutter 50 and 51.

The stable PPA of elementary has only seven sources for `resolute` today:
`gala`, `io.elementary.settings`, `granite7`, `elementary-icon-theme`,
`livechart2`, `pantheon-wayland-1` and `vala-language-server`. It publishes 84
for `noble`. This changes the note in `tunaos.toml`, which says that the PPA
has nothing for `resolute`.

### Design choices

| Question | Options | Lean |
| :--- | :--- | :--- |
| Display manager | GDM from the base, or LightDM with `io.elementary.greeter` | Start with GDM. The base ships it and the session needs one `wayland-sessions` entry. LightDM costs a block like `kde_sddm_integration`, about 500 lines of rootfs glue, and the Vala binding gap. |
| Runtime | Reuse `gnome-desktop-runtime` for mutter, GTK 4 and `gsd`, or ship a Pantheon runtime | Reuse first. `gala` links libmutter 18, and the content snap already carries it. Add a small Pantheon content snap for granite, stylesheet and icons. |
| Session start | Wrapper script as KDE does | Same. Note that GDM starts a literal `gnome-session`. Pantheon's session also uses it. The thin base re-homes this to `gnome-content-launch`. A Pantheon session must use the same hook. |
| First boot | `ubuntu-desktop-init` (shared) or Pantheon initial setup | Shared snap first. It is the same for GNOME and KDE images. |
| Release pins | Release tags or `main` | `main`, pinned by commit. Two release tags do not build on mutter 50. Athens already pins `main`. |
| Upstream or patch | Ask Canonical for a third desktop, or carry a patch | Carry a patch. A patch on a pinned commit needs no other party. Never post to Canonical from this repository. |

### Work breakdown

Sizes are estimates, not measures.

| Step | Work | Done when | Size |
| :--- | :--- | :--- | :--- |
| 0 | This probe | The shell compiles on 26.04 and `snapcraft` packs it | Done |
| 1 | Pantheon content snap | Granite 6 and 7, stylesheet, icons, wallpapers and fonts in one snap with a content slot | Days |
| 2 | Session snap | `gala`, `wingpanel`, dock, notifications, portals, polkit agent and `dconf` as apps, with slots, plugs and a launcher | One to two weeks |
| 3 | Image glue | A `pantheon` branch in `build.sh` and `build-snaps.sh`, a model file, `pantheon_gadget_connections`, the session entry | Days |
| 4 | Fork of `snapd` | Complain-mode run, then the missing AppArmor rules. KDE needed at least five commits. | One to three weeks |
| 5 | Settings | Switchboard and the plugs that work without root-only services | Days to weeks |
| 6 | TunaOS gate | `desktop: pantheon` in `ubuntu-core-desktop-image.yml`, gate on a `gala` process, screenshots | Days |
| 7 | Login screen | LightDM and the greeter, if GDM is not enough | One to two weeks |

### Risks

- **Releases lag libmutter.** `wingpanel` 8.0.4 and `greeter` 8.1.2 fail.
  The mutter of 26.04 is too new for them.
- **Main needs newer tools.** `wingpanel` main needs a newer `gtk4` Vala
  binding than 26.04 has. `greeter` main needs the LightDM Vala binding.
  Athens builds both toolchains from source. A snap must do the same.
- **No stable base.** The archive has no Pantheon. The PPA has seven sources
  for `resolute`. Each part is a source build that we own.
- **GNOME underneath.** Pantheon uses `gnome-session`, `gsd` units,
  `gnome-keyring` and a GNOME portal stack. Each one runs confined here, and
  the GNOME session needed 72 apps to do it.
- **Confinement debugging is slow.** Upstream still has open AppArmor
  backlogs for both desktops (issues `20261109` and `20260918`).
- **One desktop per image.** Upstream notes that two sessions on one image
  are not supported (issue `20260922`).
- **Grade and updates.** The same limits as GNOME and KDE apply. The image is
  `dangerous` and gets no store refresh.
- **Names.** "Pantheon" and "elementary" are the names of other projects.
  A TunaOS product name for this image is an owner decision.

### The minimal experiment

The workflow `.github/workflows/ucd-pantheon-probe.yml` runs by hand. It has
`contents: read` and publishes nothing. It has two jobs.

1. `libs` compiles each Pantheon component in an `ubuntu:26.04` container. It
   tries the newest release tag, then `main`.
2. `snap` packs `experiments/ucd-pantheon/snap/snapcraft.yaml` with
   `snapcraft` on the `ubuntu-26.04` runner. The snap has base `core26` and
   builds granite 6, `pantheon-wayland`, `gala` and the settings daemon.

Result of run [46065468620](https://github.com/tuna-os/tunaOS/actions/runs/46065468620)
on 2026-11-27 (both jobs green; the workflow ran from a pull request trigger
that the merged version no longer has):

| Component | Release tag | Tag builds | `main` builds |
| :--- | :--- | :--- | :--- |
| granite | 6.2.0 | yes | not tried |
| pantheon-wayland | 1.1.0 | yes | not tried |
| gala | 8.6.2 | yes | not tried |
| wingpanel | 8.0.4 | no: no supported mutter library | no: `gtk4` Vala binding lacks `gtk_interface_color_scheme` |
| greeter | 8.1.2 | no: no supported mutter library | no: Vala binding `liblightdm-gobject-1` missing |
| settings (Switchboard) | 8.0.3 | yes | not tried |
| settings-daemon | 8.5.0 | yes | not tried |
| notifications | 8.1.2 | yes | not tried |
| portals | 8.2.0 | yes | not tried |
| pantheon-agent-polkit | 8.1.0 | yes | not tried |
| dock | 8.3.3 | yes | not tried |
| stylesheet | 8.2.2 | yes | not tried |
| default-settings | 8.1.1 | yes | not tried |
| session-settings | 8.1.0 | no: needs the files of `gnome-settings-daemon` | yes |

The probe builds granite 6, `pantheon-wayland` and `gala` first and installs
them. The probe container does not hold `gnome-settings-daemon`, so the
`session-settings` result at the release tag is a gap of the probe.

The `snap` job packed `pantheon-desktop-session_experiment_amd64.snap`
(4.3 MiB, base `core26`, `devmode`). It holds `gala`, `gala-daemon`,
`gala-daemon-gtk3`, `libgala` and `io.elementary.settings-daemon`. The
first run failed on the missing `meson-deps` part. Later runs failed on
`desktop-file-utils`, on the Vala search path for the staged `granite`, and
on a stage package that `snapcraft` could not find. Each fix is in the
workflow history. So the lessons for a real snap are these: stage parts need
`XDG_DATA_DIRS` set for `valac`, and runtime libraries need a separate step.

What the probe does not show:

- It does not start a session. No picture exists, because nothing boots.
- It does not use confinement. The snap uses `devmode`.
- It does not test the greeter, `wingpanel` or Switchboard in a snap.

The next experiment is a session snap that starts `gala` on a GDM seat. A
patched `build.sh` puts it into an image. A gate waits for a `gala` process,
as the GNOME and KDE gates do. That needs steps 1 to 3 and part of step 4.
