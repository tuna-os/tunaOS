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

## Practices to borrow

1. **Boot gate before publish.** Build a throwaway image with a gate account.
   Boot it headless. Fail the run if the session is missing. We have this in the installer
   e2e harness. Apply the same rule to every image we publish, not only the
   installer medium.
2. **Two boots for a slow first boot.** Wait for the first-boot seed on a cold
   boot. Reboot, and then check the session. This avoids a timeout that has
   nothing to do with the image.
3. **Check the real mode.** The kernel
   command line of the first boot can show an old mode. The install
   environment also runs `sshd`. An SSH check can then test the wrong system.
   Check the run-mode evidence.
4. **Disposable images.** QEMU `cache=unsafe` and four vCPUs cut the
   first-boot time on a slow runner.
5. **PNG screendumps.** QEMU 10.2.1 writes a sheared PPM screendump when the
   width is not divisible by 4. Our harness uses PPM at 1280 pixels, which is
   safe today. Use `screendump … format=png` if the screen size ever changes.
6. **One manifest with each release.** Their release has `SHA256SUMS` and a
   `manifest.txt` with the commit and every snap version. Our
   `docs/matrix-provenance.json` is the equivalent.
7. **Land fixes in git.** A change in a live VM is not a fix.
   Their `AGENTS.md` says so.

Already done here: one script with per-desktop functions
(`manifests/desktops/*.yaml`), and the display manager of each desktop
(`display_manager` in every manifest).

## Variant plan

Stage 1 lists the upstream images in the TunaOS image matrix as a disk-image
variant. The record points to the Canonical release and reports its latest
build. We do not build the image.

Stage 2 builds the image in TunaOS CI. It reuses the Canonical release snaps,
the `build.sh` flow and the boot gate, on our runners. It needs a runner with
KVM and the `ubuntu-image` snap. It publishes only after the owner agrees.

Stage 3 would add the TunaOS brand and the TunaOS installer. That needs a model
and snaps that we control. It also needs a decision on the brand account in
the Snap Store.

Revisit the OCI question only if Canonical ships an OCI form of
`core26-desktop`.
