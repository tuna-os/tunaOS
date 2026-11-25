# Investigation: Ubuntu Core as a TunaOS base (#4930)

Status: **investigation only.** Nothing here was built or booted. The sources are
[canonical/ubuntu-core-desktop](https://github.com/canonical/ubuntu-core-desktop)
(README, `build.sh`, `docs/models.md`, the model JSON, `build-image.yaml`),
read on 2026-11-25, and this repository's `Containerfile.ubuntu`.

## Recommendation

**Do not use Ubuntu Core as a base image. Keep the Ubuntu variants on the stock
`ubuntu` OCI image, and borrow three practices from the Canonical repo.**

## Why Ubuntu Core does not fit

TunaOS builds an OCI image from a `Containerfile`, and `bootc` boots it. Ubuntu
Core is a different kind of system.

| | TunaOS (`Containerfile.ubuntu`) | Ubuntu Core Desktop |
|---|---|---|
| Unit of build | OCI image, `FROM ubuntu:<release>` | Signed snap model (`model.json`) plus snaps |
| Packages | `apt`, deb archive | Snaps only: base, gadget, kernel, `snapd`, session |
| Image tool | `podman build`, then `bootc` | `ubuntu-image` writing `pc.img` |
| Updates | `bootc upgrade` from a registry | `snapd` refreshes from the Snap Store |
| Root filesystem | composefs, built from the image | `core26-desktop` base snap |
| Signing | cosign on the OCI image | Canonical brand account key, signed via an internal RT request |

Four things block a straight swap.

1. **Ubuntu Core has no OCI base image.** A `FROM` line has nothing to name.
   Canonical assembles the image from snaps. It does not use layers.
2. **Our package model would not survive.** Variants install deb packages with
   `apt` (`build_scripts/`, `manifests/desktops/`). On Core, everything is a
   snap, and desktop apps need the confined session snaps.
3. **The brand account must sign the model.** The Canonical repo asks
   Canonical IS to sign each model change (`docs/models.md`). TunaOS has no
   brand account. A `dangerous` grade model skips this, but it cannot be
   published as a supported image.
4. **The Canonical repo itself is not a working build chain yet.** Its
   `build-image.yaml` only runs `./build.sh --help`. The comment there says
   there is no public source for the base, gadget and snapd snaps and the
   account key. It also leaves root open with a blank password as a stop-gap.

A bootc-on-Core hybrid is not worth it. Both sides own `/usr`, the boot chain
and the update path, so they would fight over each.

## Practices worth borrowing

1. **One script, per-desktop functions.** `build.sh` shares one flow between
   GNOME and KDE and isolates the differences in `desktop_*` functions chosen by
   `--desktop`. Our `manifests/desktops/*.yaml` and `install-desktop.sh` already
   do this. No change needed.
2. **No host-specific values in the build script.** Keys, passwords and account
   details are parameters, never defaults, so the script is publishable.
   Worth an audit of our `Justfile` and `scripts/` for hardcoded defaults.
3. **A pinned model file per image, with a revision and timestamp.** Each change
   bumps `revision` and `timestamp`. Our equivalent is `image-versions.yaml` and
   `docs/matrix-provenance.json`. A per-image revision counter in the provenance
   file would make "what changed in this image" easier to answer.
4. **Document the desktop and display-manager pairing.** Their README states
   that mixing a display manager with the wrong session is unsupported. Our
   desktop manifests could state the same pairing explicitly.

## What to do instead

- Track Ubuntu 26.04 through `Containerfile.ubuntu` (`grouper`), as today.
- Open separate issues for items 2 to 4 above if wanted. Each is small.
- Revisit Ubuntu Core only if Canonical publishes the base, gadget and snapd
  snaps with a public signing path, or ships an OCI form of `core26-desktop`.
