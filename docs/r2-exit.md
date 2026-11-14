# R2 exit plan for live ISOs

The goal is that nobody needs an R2-hosted native ISO. The browser builder at
`iso.tunaos.org` builds each ISO on demand. A guest test with strict checks proves each
cell. This page records what still writes to R2, what remains after the amd64
cutover, and how to remove the uploads safely.

This page is a proposal. It deletes nothing from R2 and removes no upload code.
Its numbers are from 2026-11-14 (`main` plus tunaOS#4603). Rebuild them from
`tunaos.toml` and `https://tunaos.org/iso-index.json` before you act.

## What still writes to `live-isos/`

| Writer | Workflow and job | Trigger | Gate |
| --- | --- | --- | --- |
| Per-flavor, nightly | `build-<variant>.yml` calls `build-variant.yml` (`build_artifacts_s2`, `_s3`, `_s4`), which calls `reusable-build-artifacts.yml` job `ISO <variant>:<flavor>`, step `Upload ISO to Cloudflare R2` | Daily `schedule`, or `publish-isos: true` | `upload-r2` is false when the matrix row has `r2_cutover` |
| Per-flavor, manual | `publish-isos.yml` (`Publish Live ISOs to R2`), jobs `Generate ISO matrix`, `<variant>:<flavor>`, `Release <variant>:<flavor>` | `workflow_dispatch` only (its cron is commented out) | Same `r2_cutover` gate; `Release` uploads to a GitHub release, not R2 |
| Grouped | `publish-iso-groups.yml` (`Publish Grouped Dedup ISOs to R2`), jobs `Generate ISO-group matrix`, `<variant>[-<suffix>]`, step `Upload ISO to Cloudflare R2` | Sunday 23:00 UTC, or `workflow_dispatch` | The group `r2_cutover` is true only if every buildable offline flavor is cut over |
| Pruner | `prune-r2.yml` (`Prune R2 retention`), job `Prune R2` | Daily 12:30 UTC | Deletes only dated objects older than 14 days |

All four call `scripts/publish-iso-r2.sh` or `rclone` and share the four `R2_*`
secrets. The pruner never deletes a `*-latest*` pointer, a name in
`retained_r2_isos`, or the object a resolver JSON names.

`retained_r2_isos` in `tunaos.toml` lists the names that stay as rollback.
The policy refuses a cutover target whose `-latest` pointer is not on the list.
A fully cut-over group must retain `<variant>[-<suffix>]-latest.iso`.
Versioned objects are optional (tunaOS#4550).

Other things also write to or read from R2, but they are not live ISOs:

- Screenshot jobs write `screenshots/` (`weekly-desktop-screenshots.yml`,
  `weekly-qcow2-screenshots.yml`, `installer-smoke.yml`,
  `installer-screenshots.yml`).
- `iso-e2e.yml` reads `live-isos/` when its source is `r2-latest`.
- The download page reads `static/iso-index.json` in `tuna-os/docs`.
  Its links point at `download.tunaos.org/live-isos/`.

## What remains after every amd64 cell is cut over

Today 17 of the 62 amd64 ISO targets are cut over. After the last one, the
amd64 matrix rows all carry `r2_cutover`. Then both amd64 publishers skip
their upload and write nothing. The grouped workflow still builds and boot-gates
the group ISO. It keeps only the signed checksum evidence, for seven days.

The frozen objects stay in R2. These are the retained `-latest` pointers, any
retained versioned objects and their `.sha256` and `.sigstore.json` sidecars.
They no longer update. They are rollback copies, and the download page can still
link them. The pruner still runs, but finds almost nothing to delete.

Two kinds of target can never reach this state.

## The 30 non-amd64 ISO targets

These are `build_image` and `build_iso` cells that build for another platform.
Each needs a receipt from its own platform. A receipt of the amd64 guest does
not prove them. `RECEIPT_BASIS` in `scripts/iso-delivery-policy.py` has an
entry for `linux/amd64` only. The kernel, bootloader and initramfs of an arm64
install differ from amd64. `linux/amd64/v2` is not in the policy's platform
table, so it cannot be a cutover target.

| Platform | Targets | Cells | R2 `-latest-<arch>` objects (2026-11-14) |
| --- | --- | --- | --- |
| `linux/arm64` | 21 | bonito: gnome, cosmic, kde, niri, xfce; bonito-rawhide: the same five; grouper: gnome, kde, xfce; albacore, skipjack, yellowfin: kde, niri each; gurnard: pantheon; marlin: gnome | 21 of 21, about 149 GB in total |
| `linux/amd64/v2` | 9 | albacore and yellowfin: gnome, kde, niri, xfce; skipjack: gnome | none |

The nightly per-flavor path is the only publisher of these. The grouped workflow is
amd64 only. The `r2_cutover` gate matches an exact variant, flavor and platform,
so it never closes an arm64 or v2 row.

### Options

| Option | Effect | Cost |
| --- | --- | --- |
| A. Keep the prebuilt path for these only | Nothing changes. Nightly jobs keep refreshing 21 arm64 pointers. | About 149 GB stored. Each night pays arm64 runner time and R2 writes. |
| B. Drop them | Stop the uploads. The last arm64 objects stay as frozen rollback. Users build arm64 in the browser, where each target is `unqualified` with `platform-has-no-receipt-basis`. | Users lose a maintained arm64 download. No arm64 install is tested. |
| C. Build an arm64 strict guest | An arm64 receipt becomes possible. Add `linux/arm64` to `RECEIPT_BASIS` and the receipt contract. Then cut over by evidence. | Large. Needs an aarch64 guest with UEFI, a GUI driver and OCR. [INFERENCE] Hosted arm64 runners give no KVM, so emulation makes each cell very slow. |

### Recommendation

1. Choose A for `linux/arm64`. Cut its cost first: publish it weekly, not nightly.
   This needs only a schedule change.
2. Choose B for `linux/amd64/v2`. R2 holds no v2 object, so nothing is lost.
   Set `build_iso = false` on those nine targets, or stop their builds.
3. Do not build option C now. Revisit it when an arm64 runner with KVM is available
   and the amd64 harness is stable. Until then arm64 keeps its native ISO.

After step 1, arm64 is the only remaining reason for `prune-r2.yml`,
`publish-isos.yml`, `scripts/publish-iso-r2.sh` and the R2 secrets.

## Safe order for removing uploads

Do each step in its own pull request. Check the result before the next one.

1. **Finish the cutover.** Every amd64 `build_iso` target has an entry in
   `cutover_targets`. Every nvidia sibling uses `inherits`. Every `-latest`
   pointer is in `retained_r2_isos`, and a `HEAD` on
   `https://download.tunaos.org/live-isos/<name>` returns 200.
2. **Rebuild the catalog.** Run the catalog sync so `iso.tunaos.org` lists each
   cell as `qualified`. Confirm one browser build still works for each variant.
3. **Check the gates.** In a dry run of `publish-iso-groups.yml` and
   `publish-isos.yml` (`skip_upload: true`), the matrix shows `r2_cutover: true`
   for every amd64 row.
4. **Retire the grouped upload.** Remove the schedule from `publish-iso-groups.yml`.
   Then remove step `Upload ISO to Cloudflare R2`.
   Keep the group build and boot gate if you still want a weekly check.
5. **Retire the manual per-flavor publisher.** Delete `publish-isos.yml`.
   Update the comments that name it in `reusable-build-artifacts.yml` and `iso-e2e.yml`.
6. **Apply the arm64 and v2 decision.** For option A, reduce the schedule.
   For option B, stop the upload in `reusable-build-artifacts.yml` and remove
   the `publish-isos` input in `build-variant.yml`.
7. **Retire the upload code.** Once no workflow passes `upload-r2: true`, delete the
   step `Upload ISO to Cloudflare R2`, the `upload-r2` and R2 secret inputs, and
   `scripts/publish-iso-r2.sh`. Update `tests/` that read these files.
8. **Retire the pruner last.** `prune-r2.yml` still cleans `screenshots/`.
   Remove only its `live-isos/` step, and keep `retained_r2_isos`, until a
   maintainer chooses to free R2 storage by hand.

Keep the `r2_cutover` gate until step 7. While a publisher exists, the gate
is what protects a retained pointer from an overwrite. The `retained_r2_isos`
list stays as long as any native ISO stays downloadable.
