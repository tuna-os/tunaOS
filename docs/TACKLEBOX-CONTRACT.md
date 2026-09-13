# Tacklebox ISO recipe contract

`scripts/build-iso-tacklebox.sh` is the TunaOS adapter for Tacklebox. The
adapter owns source-image resolution, customization files, and output naming;
Tacklebox owns turning the recipe into a bootable ISO. The generated
`.build/iso-tacklebox/<variant>-<flavor>/recipe.json` is the boundary between
those responsibilities.

## Recipe shape

The adapter emits one JSON object with these fields:

| Field | Producer | Contract |
| --- | --- | --- |
| `media_name` | TunaOS | Stable human-readable name: `tunaos-<variant>-<flavor>`. |
| `size` | TunaOS | `10G`; the target filesystem must have room for the image and live payload. |
| `shared_store.format` | TunaOS | `ext4`; Tacklebox uses the shared store for the bootable environment. |
| `kargs` | TunaOS | Array of kernel arguments. `console=ttyS0` is required for serial diagnostics in CI. |
| `bootable_environments` | TunaOS | Exactly one live environment for the selected variant/flavor. |
| `offline_payloads` | TunaOS | Exactly one payload mapping for the same source image, using the canonical GHCR ref. |

The environment object contains:

- `id`: `<variant>-<flavor>`.
- `image`: the resolved source image returned by `tunaos_image_ref`.
- `desktop`: the session-manager name (`gnome`, `kde`, `niri`, `cosmic`, or
  `xfce`) inferred from the flavor.
- `live_customize`: a one-item array containing the generated
  `customize-live.sh` path.
- `modes`: exactly `["live"]` for this adapter.

The payload mapping uses `source` equal to the resolved image and `ref` equal
to the canonical published `ghcr.io/<owner>/<variant>:<tag>` reference. This
keeps local builds and registry builds consistent with the image reference
embedded in the installed system.

## Invariants

Changes to the adapter must preserve these invariants:

1. The source image and offline payload refer to the same build input.
2. The environment is live-only and has one customization entry.
3. The customization directory is private to the build output directory; a
   developer-only `.enable-sshd` marker must never modify the source tree.
4. The recipe path and output directory are passed to the same Tacklebox
   invocation.
5. The final ISO is copied to the repository root using the filename contract
   consumed by publish and end-to-end workflows:
   `<variant>-<flavor>-<VERSION_ID>-<arch>.iso`.

Tacklebox changes that alter the accepted recipe fields or the meaning of
these invariants require updating this document and the adapter's tests in
the same change.

## Environment contract

The recipe is not the only input Tacklebox reads. Tacklebox also takes
per-build knobs from its environment — `TBOX_CUSTOMIZE_TIMEOUT` bounds the
live-customize script, `TBOX_CUSTOMIZE_NETWORK=host` gives that script's
container the host network — and TunaOS runs Tacklebox two different ways:

- `TACKLEBOX_FROM_SOURCE=1` builds and runs it as a host binary at the SHA
  pinned in `image-versions.yaml`. An ordinary child process, so it inherits
  the environment.
- otherwise `tunaos_run_tacklebox` runs the published container image, and
  `podman run` starts from the image's environment rather than the caller's.

`scripts/lib/tacklebox.sh` closes that gap by forwarding every **exported**
variable whose name begins with `TBOX_` into the container with an explicit
`--env`. The forwarding matches on the prefix and nothing else, so a knob
added to Tacklebox reaches TunaOS builds with no change on this side; the
names TunaOS sets for a given job live in that job's workflow. Two
consequences to keep in mind:

1. A knob must be **exported**, not just assigned, or neither path sees it.
2. `TBOX_*` is a build-knob namespace. Values are echoed into the build log
   for diagnosis, so credentials must never be passed under that prefix.

`--env-host` is deliberately not used: it would hand the Tacklebox container
the whole runner environment, `GITHUB_TOKEN` and registry logins included.

One knob does not exist yet. Tacklebox bounds the `podman commit` that
follows live-customize with a literal `600`, and tunaOS#2034 asks for that
bound to become settable the way `TBOX_CUSTOMIZE_TIMEOUT` already is. Until
it lands, a commit that needs longer than 600s and a commit that has wedged
are indistinguishable from this side — the ISO failures in tunaOS#1893 are
all of that shape. When it lands, setting it per job is the only change
TunaOS needs.

## Validation boundary

The adapter's shell tests validate the generated recipe shape without pulling
an image or running privileged filesystem operations. Full compatibility is
validated by the live ISO and ISO E2E workflows, which exercise Tacklebox with
the pinned version selected by `image-versions.yaml` unless an explicit
workflow override is supplied.
