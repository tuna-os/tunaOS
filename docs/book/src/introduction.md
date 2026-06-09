# Introduction

Welcome to TunaOS — a curated collection of Cloud-Native Enterprise Linux OS Images built on modern container technology.

## What is TunaOS?

TunaOS produces **bootc-based desktop operating system images** for Enterprise Linux platforms. Each image is an OCI container that can be:

- **Booted directly** via `bootc` on bare metal or VMs
- **Converted to an ISO** for traditional installation
- **Converted to a disk image** (QCOW2, raw) for VM usage
- **Switched to in-place** on an existing bootc system

The goal: bring a modern desktop experience to Enterprise Linux — **stable, immutable, and up-to-date**.

## Architecture

TunaOS images are built in layers:

```
┌─────────────────────────────────────┐
│         DE Stage (GNOME/KDE/…)       │  ← Desktop packages + theming
├─────────────────────────────────────┤
│       Base Stage (no-DE common)      │  ← System packages, services, brew
├─────────────────────────────────────┤
│    Enterprise Linux Base (bootc)     │  ← AlmaLinux / CentOS Stream / Fedora / RHEL
└─────────────────────────────────────┘
```

Optional hardware layers sit between base and DE:

```
DE Stage
  ↑
Base-{hwe|gdx} Stage   ← HWE kernel or NVIDIA drivers
  ↑
Enterprise Linux Base
```

**Key technologies:**

| Component | Purpose |
|-----------|---------|
| [bootc](https://github.com/bootc-dev/bootc) | Bootable OCI containers — replaces traditional package-based OS |
| [Podman](https://podman.io) | BuildKit-compatible container build engine |
| [Flathub](https://flathub.org) | Preconfigured Flatpak remote for desktop apps |
| [Homebrew](https://brew.sh) | CLI package manager baked into every image |
| [tacklebox](https://github.com/tuna-os/tacklebox) | ISO and disk image generation from bootc containers |

## Supported Variants

| Variant | Base OS | Status | Platforms |
|---------|---------|--------|-----------|
| **Yellowfin** | AlmaLinux Kitten 10 | Stable | x86_64, x86_64/v2, ARM64 |
| **Albacore** | AlmaLinux 10 | Stable | x86_64, x86_64/v2, ARM64 |
| **Skipjack** | CentOS Stream 10 | Beta | x86_64, ARM64 |
| **Bonito** | Fedora 44 | Development | x86_64, ARM64 |
| **Redfin** | RHEL 10 | Local-build only | x86_64, ARM64 |

## Desktop Environments

| Tag | Desktop |
|-----|---------|
| `gnome` | GNOME (stable) |
| `gnome50` | GNOME 50 (latest) |
| `kde` | KDE Plasma |
| `cosmic` | COSMIC Desktop |
| `niri` | Niri (tiling Wayland compositor) |

## Hardware Variants

| Suffix | Description |
|--------|-------------|
| *(none)* | Standard kernel |
| `-hwe` | Hardware Enablement — newer kernel for recent hardware |
| `-gdx` | NVIDIA drivers + CUDA for graphics/AI workloads |
| `-gdx-hwe` | NVIDIA + CUDA on HWE kernel |

Example tags: `yellowfin:gnome`, `albacore:kde-gdx`, `skipjack:niri-hwe`

## Immutable Design

TunaOS images are **immutable at runtime**. The root filesystem is read-only; changes are applied via layering:

- **System packages**: Added at build time via `dnf` in Containerfile stages
- **Desktop apps**: Installed at runtime via Flatpak (Flathub)
- **CLI tools**: Installed at runtime via Homebrew (`/var/home/linuxbrew`)
- **Configuration**: Overlay files in `/etc` via `system_files/`

This design provides:
- **Atomic updates**: `bootc upgrade` applies a new image as a single transaction
- **Rollback**: `bootc rollback` reverts to the previous deployment
- **Reproducibility**: Images are built from Containerfiles tracked in git

## Comparison

| | TunaOS | Traditional EL | Fedora Silverblue |
|---|---|---|---|
| **Base** | AlmaLinux/CentOS/Fedora/RHEL | RHEL/AlmaLinux | Fedora |
| **Desktop** | GNOME/KDE/COSMIC/Niri | GNOME (stock) | GNOME |
| **Updates** | OCI image-based (atomic) | DNF (package-by-package) | rpm-ostree (layered) |
| **Rollback** | `bootc rollback` | No native rollback | `rpm-ostree rollback` |
| **Immutable** | Yes | No | Yes |
| **Container-native** | Yes (OCI images as OS) | No | Partial |

## Getting Started

1. **[Install from ISO](#)** — download a pre-built ISO and install
2. **[Build your own](building.md)** — build images locally with `just` and `podman`
3. **[Switch an existing system](building.md#switching-an-existing-system)** — `bootc switch` from another bootc-based OS
