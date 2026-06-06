# Live ISO Generation

TunaOS uses a modern, container-native approach to generate bootable Live ISOs from its `bootc` container images. This process is based on the logic pioneered in the `bootc-isos` project and is now integrated into the official `bootc-image-builder`.

## Overview

The generation process consists of three main stages:

1.  **Installer Image Building**: A specialized "installer" container is built on top of the base TunaOS image. This layer adds `dracut-live`, `livesys-scripts`, and other components necessary for a live-booting environment.
2.  **ISO Composition**: The official `bootc-image-builder` container is used to convert the "installer" container into a bootable ISO. It leverages `osbuild` to compose the final artifact.
3.  **Verification**: The generated ISO is verified using a Lima VM to ensure it boots correctly to a desktop or shell.

## Prerequisites

- `podman` (rootful required for the ISO composition step)
- `just` command runner
- `lima` (for verification)
- `rclone` (optional, for R2 upload)

## Building a Live ISO

To build a Live ISO for a specific variant and flavor, use the `live-iso` Just recipe:

```bash
# Example: Build Yellowfin GNOME Live ISO
just live-iso yellowfin gnome
```

By default, this will:
1. Build the base container image (if not already present).
2. Build the live-installer container.
3. Run `bootc-image-builder` to generate `yellowfin-gnome-live.iso`.

### Customizing the Build

You can specify the repository source (`local` or `ghcr`), the image tag, and the output format:

```bash
# Build from GHCR images
just live-iso variant=albacore flavor=kde repo=ghcr tag=latest
```

## Troubleshooting Mirror Issues

If you encounter "No more mirrors to try" errors during the `osbuild` phase (common in local environments with unstable mirror access), it is recommended to run the build in **GitHub CI**.

The GitHub Action workflow `.github/workflows/live-iso-bootc.yml` is configured to handle these builds in a clean environment with reliable network access.

## Verification

After building the ISO, you can verify it boots using Lima:

```bash
just verify-live-iso yellowfin-gnome-live.iso
```

This will spin up a headless Lima VM using the ISO and check if it reaches a running state within 60 seconds.

## Publishing to R2

If the `UPLOAD_R2` environment variable is set to `true`, the build script will automatically attempt to upload the finished ISO to Cloudflare R2 using `rclone`.

```bash
export UPLOAD_R2=true
just live-iso yellowfin gnome
```
