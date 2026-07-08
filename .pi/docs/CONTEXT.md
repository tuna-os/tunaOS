# CONTEXT.md — TunaOS Domain Glossary

> This file is a **glossary, not a spec**. It defines the canonical terms used throughout this codebase.  
> Implementation details, roadmaps, and build instructions live elsewhere.  
> Created via `/grill-with-docs` on 2026-06-11.

## Image

The concrete OCI artifact published to GitHub Container Registry, uniquely identified by a **variant**, **desktop**, and optional **flavor**.

Canonical form: `ghcr.io/tuna-os/<variant>:<desktop>[-<flavor>]`

Examples:
- `ghcr.io/tuna-os/yellowfin:gnome` — basic GNOME desktop on Yellowfin
- `ghcr.io/tuna-os/albacore:gnome-hwe` — GNOME with hardware enablement on Albacore
- `ghcr.io/tuna-os/yellowfin:kde-nvidia` — KDE with NVIDIA drivers on Yellowfin

## Variant

A named product line mapping to a specific upstream distribution. Each variant has its own Containerfile chain and CI build workflow.

| Variant | Upstream | Status |
|---------|----------|--------|
| Yellowfin | AlmaLinux Kitten 10 | Stable |
| Albacore | AlmaLinux 10 | Stable |
| Skipjack | CentOS Stream 10 | Stable |
| Bonito | Fedora 44 | Stable |
| Grouper | Ubuntu 26.04 | Experimental (RFC 010) |
| Redfin | RHEL 10 | Alpha (local-build only) |

Variants can share desktops and flavors, but not all combinations are built for all variants.

## Desktop

A desktop environment shipped within an image. The build pipeline installs and configures the DE at Stage 2.

| Tag | Desktop Environment | Notes |
|-----|-------------------|-------|
| `gnome` | GNOME (distro default) | The version shipped by the upstream (GNOME 47 on EL10) |
| `kde` | KDE Plasma | |
| `cosmic` | COSMIC Desktop | |
| `niri` | Niri | Tiling Wayland compositor |
| `xfce` | XFCE | xfwl4 Wayland compositor on EL10/Fedora; X11 stack on Ubuntu |

## Flavor

A hardware modifier appended to a desktop tag with `-`. Flavors add kernel modules, drivers, or other hardware-specific layers at Stage 3.

| Suffix | Name | Description |
|--------|------|-------------|
| *(none)* | Standard | Distro default kernel + drivers |
| `-hwe` | Hardware Enablement | Newer kernel stack for recent hardware |
| `-nvidia` | NVIDIA | NVIDIA drivers + CUDA. Formerly `-gdx` |
| `-nvidia-hwe` | NVIDIA + HWE | NVIDIA drivers + CUDA on the HWE kernel. Formerly `-gdx-hwe` |

## Build Stage

A phase of the CI pipeline. Images chain through stages: each stage layers additional content onto the previous stage's output.

- **Stage 1** — Base image (no desktop environment)
- **Stage 2** — Desktop environment installation
- **Stage 3** — Hardware layers (HWE kernel, NVIDIA drivers)

ISOs and QCOW2s are produced per-stage, not gated on all later stages completing.

## Testing Tag

The unverified stream tag `:<desktop>[-<flavor>]-testing` on GHCR. Every CI
build pushes its multi-arch manifest here first; CI stage chaining consumes it.
The bare tag is only written by **Promotion**.

## Boot Gate

The QEMU verification between build and publish: an image is installed to a
disk with bootc and booted (`scripts/iso-e2e.sh --disk`), or a live ISO is
booted directly, and must reach a graphical/ready state (serial marker or
screenshot-sanity fallback). Failing the gate blocks Promotion (images) or
upload (ISOs).

## Promotion

Copying a verified `-testing` manifest onto the user-facing bare tags
(`:<flavor>`, `:<flavor>-YYYYMMDD`, per-arch). Performed by the "Promote Tags"
job in `reusable-build-image.yml`, only after the Boot Gate passes and all of
the variant's platforms built.

## Rechunking

Using [coreos/chunkah](https://github.com/coreos/chunkah) to reassemble an image's OCI layers for more efficient container pulls. Applied to published images, not a separate build step.

## Tacklebox

An external CLI tool in the `tuna-os` org ([tacklebox](https://github.com/tuna-os/tacklebox)) that consumes tunaOS OCI images to produce bootable ISOs and QCOW2 VM images. CI invokes tacklebox during the ISO publishing workflow.

## Hive

The AI-driven automated development platform ([hanthor/hive](https://github.com/hanthor/hive)) that orchestrates multi-agent development against this repo. Hive agents (guide, architect, sec-check, quality, ci-maintainer, strategist) run on a local Kubernetes cluster and contribute via GitHub PRs. Hive configuration is external to this repo; only the PRs it creates are visible here.

## External dependencies

- **bootc** — Container-native boot mechanism. All tunaOS images are bootc-based.
- **bootc-image-builder** — Builds bootc images from Containerfiles.
- **GHCR** — GitHub Container Registry (`ghcr.io/tuna-os`), where all images are published.
