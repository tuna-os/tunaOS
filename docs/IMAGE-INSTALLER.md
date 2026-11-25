# Image installer e2e

CI proves the hybrid medium boots, installs, and updates. It boots the
exact bytes as a CD and as a USB stick. It then runs the full install for
each promoted cell.

## Cells

`scripts/installer-e2e/matrix.py` reads the resolved cells of
`scripts/lib/installer_medium.py`. The nightly run takes the promoted cells.
A workflow dispatch with a cell name takes any supported cell, promoted or
not. `installer-medium/docs/cells.md` lists every cell and its status. A new
promoted cell joins the nightly run with no workflow edit.

| Desktop of the cell | GUI input | Display |
|---|---|---|
| `gnome`, `tuna`, `pantheon`, `kde`, `xfce` | AT-SPI matchers | VGA |
| `cosmic`, `niri` | OCR fallback | virgl |

The desktop decides the input path, not the full flavor name:
`cosmic-nvidia` uses the OCR fallback as `cosmic` does. Cosmic and Niri have
no tested AT-SPI tree, and their compositors need a render node.

The baseline and candidate digests come from the published ref of the cell.
`bonito-rawhide:gnome` publishes as `bonito:gnome-rawhide`.

## The seven stages

1. Live boot.
2. Installer pages.
3. Install.
4. TPM unlock or recovery key.
5. First-boot setup.
6. Desktop plus `bootc status`.
7. `bootc switch` plus rollback.

Stage 3 also proves a live file survives the install on btrfs cells. The
seed keeps the live session, so the file must persist. On EL10 cells the
reboot handoff is a TODO marker until #4908 and #4909 land.

## Publish

CI publishes only after all stages pass on a cell. It pushes the OCI
layout from `chunk-publish.py` to `ghcr.io`, then signs the digest with
keyless cosign. The receipt holds the digest, the config hash, and the
verify output. Retention keeps the latest five dated tags per cell.

## Cost

Each cell runs two boots in one job. The job budget caps a cell at six
hours. Two cells run side by side, so the nightly run ends in about six
hours. Real times land in `comparison.json` after the first green run.

## Local checks

Run the full loop with no KVM or root:

```bash
python3 scripts/installer-e2e/run_e2e.py --list-stages
python3 scripts/installer-e2e/run_e2e.py --dry-run --cell tromso:kde --medium out.iso
python3 -m pytest tests/test_installer_e2e_matchers.py tests/test_installer_e2e_harness.py -q
actionlint .github/workflows/image-installer.yml
```

VM boots, builds, and the publish path run in CI only.
