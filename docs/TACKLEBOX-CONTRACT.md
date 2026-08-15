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

## Validation boundary

The adapter's shell tests validate the generated recipe shape without pulling
an image or running privileged filesystem operations. Full compatibility is
validated by the live ISO and ISO E2E workflows, which exercise Tacklebox with
the pinned version selected by `image-versions.yaml` unless an explicit
workflow override is supplied.
