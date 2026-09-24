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
these invariants need updating this document and the adapter's tests in
the same change.

## Environment contract

Tacklebox also reads per-build settings from its environment.
`TBOX_CUSTOMIZE_TIMEOUT` sets the limit for the live-customize script.
`TBOX_CUSTOMIZE_COMMIT_TIMEOUT` sets the limit for the `podman commit` after
that script. `TBOX_CUSTOMIZE_NETWORK=host` gives the script container the host
network.
TunaOS runs Tacklebox in two ways:

- With `TACKLEBOX_FROM_SOURCE=1`, the adapter builds Tacklebox at the SHA in
  `image-versions.yaml` and runs it as a host binary. The binary is a child
  process, so it gets the environment of the caller.
- Otherwise, `tunaos_run_tacklebox` runs the published container image.
  `podman run` starts from the environment of the image, not of the caller.

`scripts/lib/tacklebox.sh` sends each **exported** variable whose name starts
with `TBOX_` into the container with an explicit `--env`. The filter uses only
the prefix. Thus a new Tacklebox setting gets to TunaOS builds with no change
here. The workflow of each job sets the values for that job. Obey these rules:

1. Export the setting. If you only assign it, neither path gets it.
2. Do not put a secret in a `TBOX_` variable. The adapter writes the names and
   values to the build log.

The adapter does not use `--env-host`. That option sends the full runner
environment into the container, including `GITHUB_TOKEN` and registry
logins.

### Commit deadline

Tacklebox sets a 600-second limit on the post-customize commit. On CI, some
large desktop layers need more time than that, also with native `overlay`
storage (tunaOS#1893). Thus the adapter sets `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`
to 1800 seconds when the caller does not set it. The rules are:

- A caller can set a different whole number of seconds. `0` removes the
  limit on the commit.
- The adapter stops with exit status 2 on a value that is not a whole number.
  Tacklebox itself ignores such a value and uses 600.
- `TUNAOS_TACKLEBOX_TIMEOUT_SECONDS` stays the limit for the full build. Thus
  a commit without its own limit cannot make the build run without end.
- The pin in `image-versions.yaml` must be at `ae93e9b` or later. Older
  revisions do not read the setting.

## Validation boundary

The adapter's shell tests validate the generated recipe shape without pulling
an image or running privileged filesystem operations. Full compatibility is
validated by the live ISO and ISO E2E workflows, which exercise Tacklebox with
the pinned version selected by `image-versions.yaml` unless an explicit
workflow override is supplied.
