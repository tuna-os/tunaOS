# Image installer e2e

CI proves the hybrid medium boots, installs, and updates. It boots the
exact bytes as a CD and as a USB stick. It then runs the full install for
each promoted cell.

## Cells

`scripts/installer-e2e/matrix.py` reads `[installer_medium]` from
`tunaos.toml`. A new cell joins every run with no workflow edit.

| Cell | Root fs | GUI input | Display |
|---|---|---|---|
| `albacore:gnome` | xfs (EL10) | AT-SPI matchers | VGA |
Cells with no tested AT-SPI tree use the OCR fallback instead. The matrix
maps `cosmic` and `niri` flavors that way for cells that declare them.
Those cells also use the virgl display path, since their compositors need
a render node.

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

## Run it from a branch

Add the label `run-installer-e2e` to a pull request that touches
`installer-medium/`, `tunaos.toml`, or the workflow file. The run starts
without a merge and never publishes. `workflow_dispatch` lists the workflow
only once its file is on the default branch.

## Publish

Dispatch runs publish nothing unless you set `publish`. The nightly
schedule is off until the first green dispatch and the owner's go-ahead.
CI publishes only after all stages pass on a cell. It pushes the OCI
layout from `chunk-publish.py` to `ghcr.io`, then signs the digest with
keyless cosign. The receipt holds the digest, the config hash, and the
verify output. Retention keeps the latest five dated tags per cell.

## Cost

Each cell runs two boots in one job. The job budget caps a cell at six
hours. Two cells run side by side, so a full run ends in about six
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
