# Testing Guide

TunaOS uses a QEMU-based end-to-end test harness to verify ISO images boot correctly and reach the live desktop environment.

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
