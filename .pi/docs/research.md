# Research: Serial Console from bootc-based Live ISO (systemd-boot + dmsquash-live)

## Summary

`console=ttyS0,115200n8` in the BLS entry's `options` **does reach the kernel** when booting via systemd-boot — the BLS `options` field IS the kernel command line (passed as EFI load options to the kernel stub). The lack of serial output is not a bootloader problem; it's a combination of `quiet` suppressing early-kernel messages and dmsquash-live's `switch_root` transition not guaranteeing a serial getty on the real root. The cmdline is delivered correctly; user-space serial output needs additional plumbing.

## Findings

### 1. BLS `options` = kernel cmdline with systemd-boot (no EFI-stub-vs-BLS split)

When systemd-boot boots a type-1 BLS entry (separate `linux`, `initrd`, `options` fields), it calls `EFI LoadImage` + `StartImage` on the kernel, passing the `options` string as the load options. The kernel's EFI stub converts these into the kernel command line, which appears in `/proc/cmdline`. There is **no separate "EFI stub cmdline"** — it's the same thing.

The distinction only matters with **UKIs** (Unified Kernel Images, type-2 BLS entries), where the `.cmdline` PE section is baked into the binary at build time. Tacklebox uses type-1 entries, so the BLS `options` field is authoritative. [Source: systemd-boot(7) man page, Boot Loader Specification](https://uapi-group.org/specifications/specs/boot_loader_specification/)

**Verdict:** The cmdline delivery is fine. The problem is downstream.

### 2. `quiet` suppresses the evidence

The typical BLS entry tacklebox generates likely includes `quiet` alongside `console=ttyS0,115200n8`. The `quiet` parameter suppresses kernel log messages (`printk` level raised), so nothing appears on serial during early boot. This is the most common reason for "no serial output" despite a correct `console=` parameter.

- Without `quiet`: kernel messages (up through `Freeing unused kernel memory`) appear on ttyS0
- With `quiet`: no kernel messages on any console until userspace writes something
- If no serial getty starts after switch_root, there's **zero output** on ttyS0 from start to finish

**Verdict:** Remove `quiet` as a diagnostic step to confirm cmdline delivery. If kernel messages appear, the cmdline is correct and the issue is user-space console setup.

### 3. dmsquash-live `switch_root` loses the serial console context

This is the core architectural issue. The boot sequence:

```
kernel (cmdline applied, console=ttyS0 active)
  → initrd (dracut, dmsquash-live mounts squashfs)
    → switch_root to real root
      → new systemd instance reads /proc/cmdline
        → systemd-getty-generator creates getty IF /dev/ttyS0 exists
```

After `switch_root`, the real root's systemd re-evaluates `/proc/cmdline`. `systemd-getty-generator` creates `serial-getty@ttyS0.service` **only if the device node `/dev/ttyS0` exists at generator time** (early boot, before modules are loaded). If the serial 8250 driver is a module (`CONFIG_SERIAL_8250=m`), `/dev/ttyS0` doesn't exist when the generator runs, so no getty is created, and user-space never writes to serial.

Even if the driver is built-in (`=y`), the generator still needs `console=ttyS0` in `/proc/cmdline` to trigger getty creation. The cmdline survives `switch_root` (it's in the kernel's buffer), so this part works. But the device node timing is the catch.

[Source: systemd-getty-generator(8) man page, kernel admin-guide/serial-console.rst](https://www.kernel.org/doc/html/latest/admin-guide/serial-console.html)

### 4. Kernel config: `CONFIG_SERIAL_8250` must be `=y`, not `=m`

For `console=ttyS0` to work at all (even for early kernel messages), the 8250 serial driver must be built into the kernel image, not loaded as a module. The kernel config directives are:

```
CONFIG_SERIAL_8250=y
CONFIG_SERIAL_8250_CONSOLE=y
```

If these are `=m`, the kernel has no serial driver during early boot, and `console=ttyS0` silently degrades — the kernel **does** register the console preference, but no output is produced until the module loads (which may never happen in a live ISO context where the module is in the squashfs that hasn't been mounted yet).

**This is the most likely root cause if even kernel messages don't appear on serial (after removing `quiet`).** Fedora/CentOS bootc images typically build these as modules for size. A live ISO needs them built-in.

[Source: Linux kernel Kconfig, drivers/tty/serial/8250/Kconfig](https://github.com/torvalds/linux/blob/master/drivers/tty/serial/8250/Kconfig)

### 5. QEMU `-append` doesn't work with UEFI + ISO boot

The suggestion to use QEMU's `-append` flag only works with **direct kernel boot** (`-kernel vmlinuz -initrd initrd.img -append "..."`). When booting via full UEFI firmware (`-bios OVMF.fd` / pflash) with `-cdrom`, the firmware loads systemd-boot from the ISO, which then loads the kernel. QEMU's `-append` is ignored because QEMU never sees the kernel load — the firmware does.

**Workaround for testing:** Use direct kernel boot to bypass the bootloader entirely:
```
qemu-system-x86_64 -kernel vmlinuz -initrd initrd.img \
  -append "root=live:CDLABEL=... rd.live.image console=ttyS0,115200n8"
```
This guarantees the cmdline reaches the kernel and provides a baseline for whether the kernel+initrd combo supports serial at all. If direct-boot serial works but ISO+UEFI serial doesn't, the problem is bootloader-specific. If neither works, the problem is kernel config or initrd.

### 6. Fixes, ordered by effort

| # | Fix | Effort | Reliability |
|---|-----|--------|-------------|
| A | Remove `quiet` from BLS options (tacklebox change) | 1-line change | Confirms cmdline delivery; still needs user-space output |
| B | Add `systemd.journald.forward_to_console=1` to BLS options | 1-line change | Forces journal output to console after switch_root; works regardless of getty |
| C | Ensure `CONFIG_SERIAL_8250=y` in the bootc image's kernel | Kernel rebuild | Required for any serial output at all if currently =m |
| D | Embed `console=ttyS0` in `loader/loader.conf` global options | 1-line change | systemd-boot passes these to ALL entries; less targeted but harder to miss |
| E | Direct kernel boot in QEMU test (bypass bootloader) | CI script change | Reliable for testing; doesn't fix the ISO for real hardware |
| F | Screenshot-based verification (status quo) | Already done | Works; slower than serial but doesn't depend on kernel config |

**Recommended path:** (A) remove `quiet` → test if kernel messages appear on serial. If yes: (B) add `systemd.journald.forward_to_console=1`. If no: (C) check kernel config, likely need serial built-in. Keep (F) as fallback — screenshot test already works.

## Sources

All sources are from training knowledge (systemd-boot(7), Boot Loader Specification, systemd-getty-generator(8), Linux admin-guide/serial-console.rst, kernel Kconfig). No external web access was available to fetch current URLs, but these are stable specifications and kernel documentation.

- Kept: systemd-boot(7) / Boot Loader Specification — authoritative on BLS options delivery
- Kept: systemd-getty-generator(8) — authoritative on console→getty mapping
- Kept: Linux kernel admin-guide/serial-console.rst — authoritative on serial console requirements
- Kept: QEMU `-append` documentation — confirmed only works with `-kernel`, not `-cdrom`
- Dropped: N/A (no web search available; all content is from training data)

## Gaps

1. **Actual kernel config of the bootc images** — Can't verify whether `CONFIG_SERIAL_8250=y` without extracting the kernel config from a built container image. Suggested next step: `podman run <image> zcat /proc/config.gz | grep SERIAL_8250` or equivalent.

2. **Exact BLS entry content** — Can't read tacklebox source to confirm whether `quiet` is included and exactly how `console=ttyS0` is placed. The tacklebox repo is not cloned locally. Suggested: clone `tuna-os/tacklebox` and inspect `internal/install/live.go` and `internal/bootloader/systemd_boot.go`.

3. **dmsquash-live dracut module specifics** — Whether the Fedora/CentOS dracut configuration strips certain kernel args during switch_root is version-dependent. Suggested: inspect `/usr/lib/dracut/modules.d/90dmsquash-live/` in the container image.

4. **OVMF serial port mapping** — TianoCore OVMF may present the serial port differently than `ttyS0` (e.g., via ACPI or MMIO). QEMU's `-serial` uses `-chardev` internally, but the I/O port mapping should be standard. Low risk but not zero.

## Supervisor coordination

N/A — research complete, no blocking decisions needed.

---

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "Wrote research.md answering: why console=ttyS0 in BLS options doesn't produce serial output from bootc-based live ISO with systemd-boot + dmsquash-live. Covered all 6 requested areas: (1) bootc ISO documentation, (2) dmsquash-live console issues, (3) systemd-boot vs GRUB cmdline delivery, (4) BLS vs EFI stub cmdline, (5) where console=ttyS0 must go, (6) workarounds including kernel config, journald forwarding, and direct kernel boot. Provided 6 fixes ordered by effort."
    }
  ],
  "changedFiles": [
    "/var/home/james/dev/tuna-os/tunaos/research.md"
  ],
  "testsAddedOrUpdated": [],
  "commandsRun": [],
  "validationOutput": [],
  "residualRisks": [
    "Actual kernel config (CONFIG_SERIAL_8250) in bootc images not verified — needs podman run check",
    "Exact BLS entry content from tacklebox not confirmed — tacklebox source not cloned locally",
    "All findings from training knowledge; no live web search available to fetch current bug reports or documentation URLs"
  ],
  "noStagedFiles": true,
  "notes": "No web_search tool available in this environment. All findings are from training knowledge of systemd-boot, Boot Loader Specification, dracut/dmsquash-live, and Linux kernel serial console mechanics. The analysis traces the full boot chain (EFI stub → kernel → initrd → switch_root → real root) and identifies the most likely failure point as the dmsquash-live switch_root transition dropping serial console context, combined with possible CONFIG_SERIAL_8250=m in the kernel. Recommended diagnostic: remove 'quiet' from BLS options as a 1-line test to confirm cmdline delivery, then add systemd.journald.forward_to_console=1 for user-space serial output."
}
```
