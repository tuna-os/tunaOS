# Code Context: dakota-iso Serial Console & QEMU E2E Test Strategy

## Files Retrieved
1. `/tmp/dakota-iso/CLAUDE.md` (lines 180–190) — live-ready.service specification
2. `/tmp/dakota-iso/CLAUDE.md` (lines 557-559) — DAKOTA_LIVE_READY troubleshooting
3. `/tmp/dakota-iso/live/src/configure-live.sh` (lines 244–269) — live-ready.service creation
4. `/tmp/dakota-iso/live/src/configure-live.sh` (lines 86–99) — debug-ssh-banner.service
5. `/tmp/dakota-iso/live/src/build-iso.sh` (lines 86–90, 176–178, 280, 286) — BLS entry with console=ttyS0 in kernel cmdline
6. `/tmp/dakota-iso/dakota/src/build-iso.sh` (lines 86–90, 178, 280) — same BLS logic, local copy
7. `/tmp/dakota-iso/scripts/plain-install-qemu.sh` (lines 87–117) — post-install BLS patch for dual console
8. `/tmp/dakota-iso/scripts/luks-install-qemu.sh` (lines 90–124) — post-install BLS patch for dual console + LUKS
9. `/tmp/dakota-iso/.github/workflows/build-iso.yml` (lines 279–329) — QEMU boot smoke test
10. `/tmp/dakota-iso/.github/workflows/build-iso-bluefin.yml` (lines 185–239) — Bluefin QEMU boot smoke
11. `/tmp/dakota-iso/.github/workflows/test-plain-install.yml` (whole file) — Plain install E2E workflow
12. `/tmp/dakota-iso/.github/workflows/test-luks-install.yml` (whole file) — LUKS install E2E workflow
13. `/tmp/dakota-iso/justfile` (lines 291–358) — `boot-iso-serial` recipe
14. `/tmp/dakota-iso/justfile` (lines 707–810) — `luks-boot-qemu-live` recipe
15. `/tmp/dakota-iso/justfile` (lines 1019–1090) — `plain-boot-qemu-live` recipe
16. `/tmp/dakota-iso/justfile` (lines 1179–1213) — `plain-verify-qemu` recipe
17. `/tmp/dakota-iso/live/src/luks-unlock.py` (lines 160–167, 262–385) — serial-based boot state detection
18. `/tmp/dakota-iso/docs/ci.md` (lines 80–87, 267–273) — CI boot verification logic + serial console troubleshooting
19. `/tmp/dakota-iso/docs/architecture.md` (lines 142–152) — live-ready.service architecture doc
20. `/tmp/dakota-iso/scripts/build-live-squashfs.sh` — embedded OCI store build (no kernel cmdline config here)

---

## Key Code

### 1. BLS Entry Kernel Cmdline — ISO Build Time (`live/src/build-iso.sh` lines 86–90, 280, 286)

```bash
# Map of arch → serial console device for kernel cmdline
declare -A SERIAL_CONSOLE
SERIAL_CONSOLE[x86_64]="ttyS0"
SERIAL_CONSOLE[aarch64]="ttyAMA0"
```

```ini
# BLS entry (line 280/286):
title   Dakota Live
linux   /images/pxeboot/vmlinuz
initrd  /images/pxeboot/initrd.img
options root=live:LABEL=DAKOTA_LIVE rd.live.image rd.live.overlay.overlayfs=1 enforcing=0 nvidia-drm.modeset=1 console=ttyS0,115200n8 console=ttyAMA0,115200n8
```

**This is the critical difference from TunaOS.** The kernel cmdline is baked into the BLS entries during ISO build. The `console=ttyS0,115200n8` parameter is NOT added via QEMU `-append` — it comes from the bootloader config inside the ISO.

### 2. live-ready.service (`live/src/configure-live.sh` lines 254–269)

```ini
[Unit]
Description=Live environment ready marker
After=display-manager.service
Requires=display-manager.service

[Service]
Type=oneshot
ExecStart=/bin/echo DAKOTA_LIVE_READY
StandardOutput=tty
TTYPath=/dev/ttyS0

[Install]
WantedBy=multi-user.target
```

Key design decisions (documented at lines 244–253):
- `StandardOutput=tty` + `TTYPath=/dev/ttyS0` — writes DIRECTLY to serial device, NOT via journal+console
- `StandardOutput=journal+console` would route to `/dev/console`, which is NOT the serial device in headless QEMU (`-display none`, `-serial file:...`)
- `WantedBy=multi-user.target` (not display-manager.service) for reliable enablement
- `After=display-manager.service` for ordering only

### 3. debug-ssh-banner.service (`live/src/configure-live.sh` lines 86–99)

```ini
[Service]
Type=oneshot
ExecStart=/bin/bash -c '... echo "DEBUG SSH READY" ...'
StandardOutput=journal+console

[Install]
WantedBy=multi-user.target
```

This uses `journal+console` (goes to /dev/console), which does NOT reach the serial log. CI checks for it as a pattern match in serial output (only works if journald pushes to console on ttyS0, which it sometimes does as a side effect).

### 4. QEMU Invocation — 3 Consistent Patterns

**Pattern A: Live ISO boot (CI smoke test, `build-iso.yml` lines 301–308):**
```bash
sudo qemu-system-x86_64 \
  -machine type=q35,accel=kvm \
  -cpu host -m 4G -smp 2 \
  "${PFLASH[@]}" \
  -cdrom "$ISO" -boot d \
  -monitor unix:/tmp/qemu-monitor.sock,server,nowait \
  -serial file:/tmp/serial.log \
  -display none -daemonize
```

**Pattern B: Live ISO with install disk (E2E tests, `justfile` ~lines 765–790):**
```bash
$QEMU \
  -machine q35 $CPU_FLAG -m 4096 -smp 4 $QEMU_ACCEL \
  -drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}" \
  -drive "if=pflash,format=raw,file=${OVMF_VARS}" \
  -drive "if=none,id=iso,file=${ISO},media=cdrom,readonly=on,format=raw" \
  -device virtio-scsi-pci,id=scsi \
  -device scsi-cd,drive=iso \
  -drive "if=none,id=disk,file=${DISK},format=raw,cache=unsafe" \
  -device virtio-blk-pci,drive=disk \
  -drive "if=none,id=scratch,file=${SCRATCH},format=raw,cache=unsafe" \
  -device virtio-blk-pci,drive=scratch \
  -netdev "user,id=net0,hostfwd=tcp::${SSH_PORT}-:22" \
  -device virtio-net-pci,netdev=net0 \
  -monitor "unix:${MONITOR},server,nowait" \
  -serial "file:${SERIAL_LOG}" \
  -display none \
  -daemonize
```

**Pattern C: Installed disk boot (post-install):**
```bash
$QEMU \
  -machine q35 $CPU_FLAG -m 4096 -smp 4 $QEMU_ACCEL \
  -drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}" \
  -drive "if=pflash,format=raw,file=${OVMF_VARS}" \
  -drive "if=none,id=disk,file=${DISK},format=raw,cache=unsafe" \
  -device virtio-blk-pci,drive=disk \
  -netdev user,id=net0 \
  -device virtio-net-pci,netdev=net0 \
  -monitor "unix:${MONITOR},server,nowait" \
  -serial "file:${SERIAL_LOG}" \
  -display none \
  -daemonize
```

**All three share**: `-serial file:...` + `-display none` + no `-append` flag.

### 5. Post-Install BLS Patch (`scripts/plain-install-qemu.sh` lines 87–117)

After fisherman install completes, the script mounts the boot partition and patches BLS entries:

```bash
# Plain install — adds dual serial+VT console
sed -i "s|^options .*|& console=tty0 console=ttyS0 rd.info systemd.journald.forward_to_console=yes|" "$entry"

# LUKS install — adds dual serial+VT console + LUKS UUID
sed -i "s|^options .*|& console=tty0 console=ttyS0 rd.luks.name=${LUKS_UUID}=root|" "$entry"
```

This is a **runtime BLS patch** because the installed system's BLS entries come from the installed image, not the live ISO's entries. The live ISO's console=ttyS0 only affects the live boot.

### 6. Boot Verification Logic — 3 Tiers

**Tier 1: Direct serial marker (`DAKOTA_LIVE_READY`)**
```bash
grep -q "DAKOTA_LIVE_READY" "${SERIAL_LOG}"
```
From `live-ready.service` writing directly to `/dev/ttyS0`.

**Tier 2: Systemd journal fallback (`Finished live-ready.service`)**
```bash
grep -q "Finished live-ready\.service" "${SERIAL_LOG}"
```
Some dev channel builds don't write to ttyS0 but journald may push the service completion message to console.

**Tier 3: SSH connectivity fallback**
```bash
sshpass -p live ssh ... true 2>/dev/null
```
Both `live-ready.service` and `debug-ssh-banner.service` use `WantedBy=multi-user.target`, so SSH being up confirms the live environment reached multi-user.target.

**Installed system verification** (after BLS patch):
```bash
# Poll serial log for systemd reaching graphical/multi-user target
grep -q "Reached target.*Graphical\|Reached target.*Multi-User\|login:" "${SERIAL_LOG}"
```

### 7. CI Acceptance Logic (`build-iso.yml` lines 312–329)

```bash
# Wait up to 5 minutes
for i in $(seq 1 60); do
  sudo grep -q "DAKOTA_LIVE_READY" /tmp/serial.log 2>/dev/null && break
  sleep 5
done
# Final gate (Tier 1 + Tier 2):
sudo grep -qE "DAKOTA_LIVE_READY|Finished live-ready\.service" /tmp/serial.log || exit 1
```

---

## Architecture

### How Serial Console Works End-to-End

```
ISO Build (build-iso.sh)                Live Boot                     CI Verification
─────────────────────────             ──────────────                  ───────────────
                                     │                         │
 BLS entry:                          │  Kernel boots with      │  QEMU: -serial file:log
 console=ttyS0,115200n8 ─────────────→│  console=ttyS0 on cmdline──→│  captures ttyS0 output
                                     │                         │
                                     │  live-ready.service:    │  grep DAKOTA_LIVE_READY
                                     │  echo DAKOTA_LIVE_READY │    OR
                                     │    > /dev/ttyS0 ────────→│  grep "Finished live-ready"
                                     │                         │    OR
                                     │  debug-ssh-banner:      │  SSH connectivity
                                     │  journal+console ───────→│  (goes to /dev/console,
                                     │                         │   not captured reliably)
```

### Critical Design Decisions

1. **No QEMU `-append` flag used anywhere.** Kernel cmdline comes from BLS entries inside the ISO.
2. **`StandardOutput=tty` + `TTYPath=/dev/ttyS0`** is mandatory for the readiness marker to appear in `-serial file:` output. `journal+console` goes to `/dev/console`, which is NOT the serial port in headless QEMU.
3. **Post-install BLS patch** is required because the installed image's BLS entries don't have `console=ttyS0`. The patch is applied via SSH after fisherman install completes and before rebooting into the installed system.
4. **Dual console (`console=tty0 console=ttyS0`)** on the installed system ensures both graphical output (for VNC/screendump) and serial output (for CI log verification).

### What Makes This Work vs. TunaOS

| Aspect | dakota-iso | TunaOS (tacklebox) |
|--------|-----------|---------------------|
| Kernel cmdline source | BLS entries in `build-iso.sh` | tacklebox BLS entries |
| console=ttyS0 in BLS | **Yes**, baked at ISO build time | **Yes**, in tacklebox BLS |
| Readiness marker | `live-ready.service` writes to `/dev/ttyS0` via `StandardOutput=tty` | `TUNAOS_LIVE_READY` (mechanism unknown) |
| QEMU serial capture | `-serial file:...` | `-serial file:...` |
| Fallback detection | SSH, `Finished live-ready.service` | N/A (blocked) |
| Kernel output visible? | **Yes** — kernel logs appear on serial | **No** — TunaOS kernel doesn't output to ttyS0 |

The underlying issue in TunaOS is likely that the kernel itself doesn't write to ttyS0 despite the `console=ttyS0` cmdline. This could be:
- Missing 8250/16550 serial driver in the kernel config
- The kernel IS writing to ttyS0 but QEMU doesn't capture it (wrong QEMU machine type)
- The BLS `console=` parameter is being overridden somewhere

---

## Start Here

Open `/tmp/dakota-iso/live/src/configure-live.sh` at line 244 — this is where `live-ready.service` is created. Then compare with TunaOS's tacklebox to see if a similar service exists. The critical test: does the TunaOS live kernel actually output to ttyS0 at all? Check kernel config for `CONFIG_SERIAL_8250`, `CONFIG_SERIAL_8250_CONSOLE`.

---

## Supervisor coordination

None needed — scouting complete.

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "Returned concrete findings with exact file paths, line numbers, QEMU invocation flags, kernel cmdline strategy, BLS patch mechanism, live-ready.service configuration, 3-tier boot verification logic, and architecture diagram. Key files: live/src/configure-live.sh:244-269, live/src/build-iso.sh:280-281, scripts/plain-install-qemu.sh:87-117, justfile:765-790, .github/workflows/build-iso.yml:301-308."
    }
  ],
  "changedFiles": [],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {
      "command": "grep -r 'live-ready|DAKOTA_LIVE_READY|ttyS0|console=ttyS|StandardOutput' /tmp/dakota-iso",
      "result": "passed",
      "summary": "Found all serial console references across 20+ files"
    },
    {
      "command": "read live/src/configure-live.sh, live/src/build-iso.sh, scripts/plain-install-qemu.sh, scripts/luks-install-qemu.sh, justfile build-iso.yml workflows",
      "result": "passed",
      "summary": "Read all critical files for complete understanding of serial console strategy"
    }
  ],
  "validationOutput": [],
  "residualRisks": [
    "TunaOS kernel may be missing CONFIG_SERIAL_8250 or CONFIG_SERIAL_8250_CONSOLE — dakota-iso relies on kernel writing to ttyS0 natively",
    "Even if tacklebox puts console=ttyS0 in BLS entries, the kernel may not honor it if serial driver isn't compiled in",
    "The live-ready.service approach (StandardOutput=tty, TTYPath=/dev/ttyS0) requires the ttyS0 device node to exist at boot time in the dracut initramfs",
    "QEMU machine type (q35) must match what the kernel expects — if the kernel is looking for ISA serial on pc-q35 rather than PCI serial, output may not appear"
  ],
  "noStagedFiles": true,
  "notes": "dakota-iso does NOT use QEMU -append to inject console=ttyS0. The kernel cmdline comes from BLS entries baked into the ISO at build time. The live-ready.service writes directly to /dev/ttyS0 using StandardOutput=tty (not journal+console). For the installed system, post-install scripts ssh in and patch BLS entries to add console=tty0 console=ttyS0 before the first reboot. This is a two-phase serial strategy: (1) ISO BLS entries for live boot, (2) runtime BLS patch for installed boot."
}
```