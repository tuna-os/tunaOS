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
