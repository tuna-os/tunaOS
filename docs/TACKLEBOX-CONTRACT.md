# Tacklebox ISO recipe contract

`scripts/build-iso-tacklebox.sh` is the TunaOS adapter for Tacklebox. The
adapter resolves images, generates customization files, and sets output names.
Tacklebox builds the recipe into a bootable ISO. The generated
`.build/iso-tacklebox/<variant>-<flavor>/recipe.json` file marks the boundary
between these systems.

## Recipe shape

The adapter emits a JSON object with these fields:

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
- `image`: the resolved source image from `tunaos_image_ref`.
- `desktop`: the session-manager name (`gnome`, `kde`, `niri`, `cosmic`, or
  `xfce`) inferred from the flavor.
- `live_customize`: a one-item array with the generated `customize-live.sh` path.
- `modes`: `["live"]` for this adapter.

The payload mapping uses `source` equal to the resolved image and `ref` equal
to the canonical published `ghcr.io/<owner>/<variant>:<tag>` reference. This
keeps local builds and registry builds consistent with the image reference
embedded in the installed system.

## Invariants

Changes to the adapter must preserve these invariants:

1. The source image and offline payload refer to the same build input.
2. The environment is live-only and has one customization entry.
3. The customization directory is private to the build output directory; a
   developer-only `.enable-sshd` marker must never change the source tree.
4. The workflow passes the recipe path and output directory to the same Tacklebox call.
5. The build script copies the final ISO to the repository root using the filename contract for publish and test workflows:
   `<variant>-<flavor>-<VERSION_ID>-<arch>.iso`.

When Tacklebox changes recipe fields or invariants, update this document and adapter tests in the same commit.

## Validation boundary

Unit tests verify the recipe structure without image pulls or root privileges.
Live ISO workflows and end-to-end test runs verify compatibility. These
workflows run Tacklebox with the version in `image-versions.yaml` unless a
workflow override exists.

