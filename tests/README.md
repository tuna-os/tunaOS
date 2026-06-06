# Test Infrastructure

This directory contains test configurations and artifacts for TunaOS image verification.

## Files

### `anaconda-ks.cfg`
Kickstart configuration for automated Anaconda installation testing. Used by the ISO end-to-end test harness to perform unattended installations into QEMU virtual disks.

### `lima-template.yaml`
Lima VM template for running and testing TunaOS images on macOS. Defines CPU, memory, and disk configuration for the Lima hypervisor.

### `live-iso-verify.yaml`
Live ISO verification manifest. Defines expected behaviors and checks for the live boot environment.

## Running Tests

See [`docs/TESTING.md`](../docs/TESTING.md) for the complete testing guide, including:
- How to run the ISO e2e harness locally
- QEMU setup requirements
- CI integration details
- Troubleshooting common test failures

## Test Harness

The main test runner is `scripts/iso-e2e.sh`, which:
1. Boots a TunaOS ISO in QEMU with OVMF (UEFI)
2. Waits for the live environment readiness signal
3. Captures a desktop screenshot via QEMU monitor
4. Collects serial console logs

CI workflow: `.github/workflows/iso-e2e.yml`
