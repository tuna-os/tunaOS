# Live ISO Generation

TunaOS generates bootable Live ISOs from its bootc container images using [tacklebox](https://github.com/tuna-os/tacklebox), a Go-based ISO and disk image builder.

## Overview

The generation process:

1. **Container image** — a TunaOS image is built (or pulled from GHCR)
2. **tacklebox** — converts the OCI image into a bootable ISO with `mksquashfs`
3. **Output** — a hybrid ISO bootable via UEFI, suitable for `dd` to USB or VM boot

```
OCI Image (ghcr.io/tuna-os/yellowfin:gnome)
        │
        ▼
    tacklebox build --iso
        │
        ▼
  yellowfin-gnome.iso
```

## Prerequisites

- `podman` (rootful required for loopback device access)
- `just` command runner
- `lima` (optional, for verification)
- `rclone` (optional, for R2 upload)

tacklebox is automatically downloaded if not installed (`ghcr.io/tuna-os/tacklebox:latest`).

## Building a Live ISO

```bash
# Build from local image
just iso yellowfin gnome

# Build from GHCR (no local build needed)
just iso yellowfin gnome repo=ghcr

# Build with a specific tag
just iso yellowfin gnome repo=ghcr tag=gnome-hwe
```

This runs `scripts/build-iso-tacklebox.sh` which:
1. Builds or pulls the container image
2. Downloads tacklebox if not present
3. Invokes `tacklebox build --iso` with the image reference
4. Outputs the ISO to `.build/live-iso/<variant>-<flavor>/`

## Demo and Testing

### Boot ISO in browser via QEMU

```bash
just demo-iso skipjack gnome
```

This builds the ISO, starts a QEMU VM, and opens a noVNC browser window.

### Boot ISO in Lima VM

```bash
just _lima-novnc myvm iso path/to/image.iso
```

### Verify ISO boots

```bash
just verify-iso path/to/image.iso
```

## ISO Contents

A TunaOS live ISO contains:

- **bootc container rootfs** — the full TunaOS image as a squashfs filesystem
- **Kernel + initramfs** — dracut-generated with live boot modules
- **systemd-boot (sd-boot)** — UEFI bootloader
- **Live environment** — boots directly to the desktop (gdm/sddm login screen)

## Troubleshooting

### "tacklebox: command not found"

tacklebox is auto-downloaded. If the download fails, build from source:

```bash
export TACKLEBOX_FROM_SOURCE=1
just iso yellowfin gnome
```

### "No more mirrors to try" during package install

This typically happens in unstable network environments. Solutions:

- **Use GHCR images**: `just iso yellowfin gnome repo=ghcr` (skips local package install)
- **Retry**: The build scripts use `dnf_retry` with exponential backoff (4 attempts)
- **Run in CI**: GitHub Actions runners have reliable network access

### SELinux denials

Builds require `--security-opt label=disable` on SELinux-enabled hosts. This is applied automatically by the Justfile. If you encounter AVC denials, ensure you're running via `just` rather than raw `podman build`.

### Disk space

- ISO builds require ~20 GB free space
- The `.build/` directory caches intermediate artifacts
- Clean up with `just clean` (preserves RPM cache) or `just clean-cache` (removes all)

### "image not known" after load

The build pipeline prunes unused images (`podman system prune -af`) to work around a BTRFS storage index bug. If you encounter this:
- Ensure you're on BTRFS or overlay storage drivers
- Run `podman system reset` and rebuild

## Publishing to Cloudflare R2

ISOs are published bi-weekly via `publish-isos.yml`. Manual upload:

```bash
export UPLOAD_R2=true
just iso yellowfin gnome repo=ghcr
```

Requires `rclone` configured with R2 credentials.

## Architecture Notes

- tacklebox replaced the previous `bootc-image-builder` (osbuild) pipeline
- Old pipeline: `Containerfile` → `image-builder-cli` → `osbuild` → ISO
- New pipeline: `Containerfile` → `tacklebox` → ISO
- tacklebox is faster (~10 min vs ~30 min) and simpler (no osbuild dependency)
- Multi-env ISOs (multiple desktop environments on one media) are supported by tacklebox but not yet used by TunaOS
