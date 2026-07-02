# Testing Guide

TunaOS uses a QEMU-based end-to-end test harness to verify ISO images boot correctly and reach the live desktop environment.

## Publish Gating

Nothing user-facing is published without a boot check. The pipeline follows
Bluefin's testing→stable promotion model:

| Artifact | Gate | Where |
|---|---|---|
| GHCR image `:<flavor>` | Manifest is pushed as `:<flavor>-testing`; a **boot gate** (`verify_boot` job) installs it to a qcow2 with bootc, boots it in QEMU (`scripts/iso-e2e.sh --disk`), and only then the promote job writes `:<flavor>`, `:<flavor>-YYYYMMDD`, and per-arch tags. `base*` flavors skip the boot gate (no desktop) and promote after manifest. | `reusable-build-image.yml` |
| ISOs on R2 / GitHub Releases | ISO is built, boot-verified in QEMU (`scripts/iso-e2e.sh`, readiness marker **or** screenshot-sanity fallback), and only uploaded if the gate passes. | `reusable-build-artifacts.yml`, `publish-iso-groups.yml` |
| PRs | Build + QEMU boot verification of the locally built image (amd64). | `reusable-build-image.yml` |

The screenshot-sanity fallback exists because the EL10 bootc kernels ship
`CONFIG_SERIAL_8250=m`, so readiness markers often never reach the serial
console; a rendered (non-blank) framebuffer captured via `-vga virtio`
counts as booted, a black/absent one fails the gate.

Run the same gates locally:

```bash
just verify-disk yellowfin.qcow2      # boot-gate a disk image
./scripts/iso-e2e.sh some.iso         # boot-gate an ISO
```

Automated screenshots: `weekly-desktop-screenshots.yml` commits real desktop
captures for every variant × DE to `docs/images/desktops/`, and
`installer-screenshots.yml` drives the GUI installer and commits the flow
captures to `docs/images/installer/` (then boot-verifies the disk the
walkthrough installed).

## ISO End-to-End Tests

The `scripts/iso-e2e.sh` script boots a TunaOS live ISO in QEMU with OVMF (UEFI), waits for the live environment to be ready, captures screenshots, and collects serial logs.

### Running Locally

```bash
# Download a pre-built ISO
wget https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso

# Run the e2e test
./scripts/iso-e2e.sh yellowfin gnome ./yellowfin-gnome-latest.iso
```

Requirements:
- `qemu-system-x86_64` with KVM support
- `qemu-utils` for `qemu-img`
- `socat` for QEMU monitor communication
- At least 4GB RAM available for the VM

### What Gets Tested

The harness validates:
1. **Boot success** — ISO reaches the live environment within 90 seconds
2. **Desktop readiness** — `gdm.service` or equivalent display manager is active
3. **No critical failures** — no `Failed to start` in the systemd journal
4. **Screenshot capture** — visual confirmation of the desktop
5. **Serial logs** — full boot output for debugging

### CI Integration

The `.github/workflows/iso-e2e.yml` workflow runs automatically:
- **On PRs** that modify build inputs (`Containerfile*`, `build_scripts/**`, `live-iso/**`, `system_files*/**`)
- **Weekly** on a schedule for regression detection
- Posts PR comments with screenshots and serial log summaries

### Test Artifacts

Test outputs are uploaded as GitHub Actions artifacts:
- `screenshot.png` — Desktop screenshot via QEMU monitor
- `serial.log` — Full boot serial console output

## Test Files

| File | Purpose |
|---|---|
| `tests/anaconda-ks.cfg` | Kickstart configuration for automated Anaconda install testing |
| `tests/lima-template.yaml` | Lima VM template for macOS testing |
| `tests/live-iso-verify.yaml` | Live ISO verification manifest |
| `scripts/iso-e2e.sh` | Main QEMU-based end-to-end test runner |
| `.github/workflows/iso-e2e.yml` | CI workflow for automated ISO testing |

## Writing New Tests

For desktop environment changes:
1. Build the ISO: `sudo just iso yellowfin gnome local`
2. Run the e2e harness: `./scripts/iso-e2e.sh yellowfin gnome .build/iso/yellowfin-gnome.iso`
3. Verify the screenshot shows the expected desktop
4. Check serial logs for any unexpected failures

## Troubleshooting

| Symptom | Likely Cause |
|---|---|
| ISO doesn't boot | Missing KVM support; try adding `--no-kvm` to the QEMU command |
| Timeout waiting for desktop | Desktop environment failed to start; check serial logs |
| `qemu-img` not found | Install `qemu-utils` package |
| Screenshot is blank | Display manager may not have started; increase timeout |
