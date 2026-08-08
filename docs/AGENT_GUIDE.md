# TunaOS Agent Guide

Authoritative reference for AI agents and contributors working on the TunaOS repository.

---

## What This Project Is

TunaOS is an **image factory** — it produces bootable OCI container images that serve as complete, immutable desktop Linux operating systems. The output is `base OS × desktop × kernel × drivers = image`, assembled by a build matrix and delivered via bootc.

See [`VISION.md`](../VISION.md) for the project philosophy.

---

## Architecture (post-refactor July 2026)

### The Manifest System

Desktop environments are defined as **YAML manifests** in `manifests/desktops/`:

```
manifests/desktops/
├── gnome.yaml   — packages, COPRs, version locks, post-install hooks
├── kde.yaml
├── cosmic.yaml
├── niri.yaml
├── xfce.yaml
├── kde-arch.yaml    — Arch/CachyOS variant (pacman)
└── kde-debian.yaml  — Debian variant (apt)
```

The generic installer `build_scripts/desktop/install-desktop.sh` reads a manifest and installs the desktop. One script, all desktops, all OS families.

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/resolve-flavor.sh` | Routes flavor → Containerfile, target, parent, flags |
| `scripts/resolve-image.sh` | Resolves image refs (base, common, brew, akmods) |
| `scripts/build-image-inner.sh` | The build engine (env-var driven, replaces old Justfile monolith) |
| `build_scripts/desktop/install-desktop.sh` | Generic manifest-driven DE installer |
| `build_scripts/lib.sh` | Shared library (OS detection, pkg abstraction, retry logic) |
| `build_scripts/desktop/gnome-extensions.sh` | GNOME extension compilation (separate cache layer) |

### Containerfiles

| File | Purpose |
|------|---------|
| `Containerfile.el10` | EL10 (dnf) build — base stage + all DE stages (yellowfin, albacore, skipjack, bonito, bonito-rawhide) |
| `Containerfile.ubuntu` | Ubuntu bootcification (grouper) |
| `Containerfile.debian` | Debian bootcification (flounder, flounder-sid) |
| `Containerfile.arch` | Arch Linux bootcification (marlin) |
| `Containerfile.gentoo` | Gentoo (source-based) bootcification (guppy) |
| `Containerfile.opensuse` | openSUSE bootcification (sailfin) |
| `Containerfile.overlay` | HWE/nvidia/cachyos layer (parameterized by `OVERLAY_TYPE`) |
| `Containerfile.custom` | User overlay build workflow (RFC #646) |
| `Containerfile.final` | Rechunk relabeling (pass 3) |

### Flavor Resolution

All flavors route through `scripts/resolve-flavor.sh`:

```bash
$ ./scripts/resolve-flavor.sh yellowfin gnome-hwe
CONTAINERFILE="Containerfile.overlay"
DESKTOP_FLAVOR="desktop"
ENABLE_HWE="1"
ENABLE_NVIDIA="0"
OVERLAY_TYPE="hwe"
PARENT_FLAVOR="gnome"
```

### Build Stages (CI DAG)

```
Stage 1: base
Stage 2: gnome, kde, niri, cosmic, xfce, base-hwe, base-nvidia  (parallel)
Stage 3: gnome-hwe, kde-hwe, gnome-nvidia, kde-nvidia, etc.     (parallel)
Stage 4: gnome-nvidia-hwe                                        (depends on stage 3)
```

Defined in `.github/build-config.yml`. The workflow is `build-variant.yml` → `reusable-build-image.yml`.

---

## Variants

| Variant | Fish | Base | Pkg Mgr | Status |
|---------|------|------|---------|--------|
| `yellowfin` | 🐠 | AlmaLinux Kitten 10 | dnf | Stable |
| `albacore` | 🐟 | AlmaLinux 10 | dnf | Stable |
| `skipjack` | 🍣 | CentOS Stream 10 | dnf | Beta |
| `bonito` | 🎣 | Fedora 44 | dnf | Beta |
| `bonito-rawhide` | 🐉 | Fedora Rawhide (rolling) | dnf | Beta |
| `sailfin` | 🦈 | openSUSE Tumbleweed (rolling) | zypper | Beta |
| `guppy` | 🌈 | Gentoo Linux (source-based) | portage | Beta |
| `grouper` | 🐟 | Ubuntu 26.04 | apt | Beta |
| `marlin` | 🚀 | Arch Linux (rolling), CachyOS kernel overlay | pacman | Beta |
| `flounder` | 🐡 | Debian 13 Trixie (stable) | apt | Beta |
| `flounder-sid` | ☢️ | Debian Sid (unstable, rolling) | apt | Beta |

---

## Setup

```bash
brew install just podman shellcheck shfmt yq
git clone https://github.com/tuna-os/tunaOS.git && cd tunaOS
just fix && just check   # validate everything
just --list              # see all commands
```

## Building

```bash
just build yellowfin gnome     # single flavor (~25 min warm cache)
just build yellowfin all       # all flavors for a variant
just build yellowfin kde linux/amd64  # specific platform
```

## Pre-Commit (mandatory)

```bash
just fix && just check
```

## Testing

```bash
just test          # bats + pytest
just test-bats     # shell script tests only
just verify-disk image.qcow2   # QEMU boot gate
```

---

## Adding a New Desktop

1. Create `manifests/desktops/<name>.yaml` with package lists per OS family
2. Add a stage in `Containerfile` (copy the pattern from existing DE stages)
3. Add the flavor to `.github/build-config.yml` for each variant

No new shell script needed. `install-desktop.sh` handles it.

## Adding a New Variant

1. Find/build a bootc-compatible base image
2. Add detection to `build_scripts/lib.sh` (IS_* flag, PKG_MGR)
3. Add the variant to `.github/build-config.yml`
4. Add pacman/apt/dnf sections to each desktop manifest
5. (Optional) Create a `Containerfile.<variant>` if bootcification is needed

---

## Key Config Files

| File | What it controls |
|------|-----------------|
| `.github/build-config.yml` | The build matrix (variants × flavors × platforms × stages) |
| `image-versions.yaml` | Pinned image digests + download versions |
| `registry-map.yaml` | Registry mirror overrides |
| `renovate.json` | Automated dependency updates (automerge all) |

---

## Community & Outreach Initiatives (#687)

Outreach and community growth initiatives are tracked centrally in [#687](https://github.com/tuna-os/tunaOS/issues/687):

- **Prerequisites & Gating**: Community outreach is gated on working ISO downloads (#561), which is confirmed operational.
- **Automated / Repository Actions**:
  - Discussions release announcements & triage response.
  - Triage and tagging of `good-first-issue` items across sub-repositories (`gtk-office-suite`, `Tavern`, `letters`).
  - Documentation and technical blog posts (e.g. Modern Enterprise Desktop & bootc on AlmaLinux).
- **External / Human Initiatives**: CFPs (All Things Open, KubeCon, Flock to Fedora), external blog/social posts, and community platform hosting require an authorized team member's external account and identity.

---

## User-Proven ISO Installs Roadmap (#763)

Canonical rollout plan for verifying end-to-end user ISO installation experience across matrix cells:

1. **Phase 1 — Monthly Backend LUKS Coverage**: Monthly 57-cell LUKS matrix sweep (#761), proving `crypto_LUKS` disk formatting, passphrase unlock, and installed boot contract.
2. **Phase 2 — Production-Quality GUI Install Driver**: OCR & framebuffer transition driver (`installer-walkthrough.py` / #577) replacing fixed sleeps.
3. **Phase 3 — One Known-Good End-to-End GUI Pilot**: Yellowfin GNOME frontend installation gate through visible GUI to installed contract.
4. **Phase 4 — Frontend Expansion**: Progressive extension across GNOME, KDE, COSMIC, Niri, and XFCE frontends.
5. **Phase 5 — ISO Builder Parity**: Unified verification contract for both CI-built and browser-built (ISO Builder #673) media via required experience manifests.

---

## Apple Silicon (Asahi Linux) Support (#781)

Umbrella initiative for making TunaOS bootable on M1/M2 Apple Silicon Macs via the Asahi stack:

- **Naming Convention**: `asahi` is a **tag suffix** (`bonito:gnome-asahi`), never a separate variant/image name.
- **Verification Harness (#776 / #910)**: Daily 35-point golden-manifest boot-chain sweep. Bonito (Fedora) and Grouper (Ubuntu) are verified 36/36 green. Remaining variants are undergoing kernel and boot-chain alignment (#777, #911, #912, #914).
- **Installer Track (`bootc-installer-asahi`)**:
  - D0: Real-image payload packaging & validation.
  - D1: Fisherman first-boot agent integration.
  - D2: `asahi-installer` JSON mode interface.
  - D3: macOS SwiftUI frontend application.
  - D4: recoveryOS UX, LUKS, and Wi-Fi configuration.
- **Constraints**: M1/M2 hardware targets only; no live-ISO path on Apple Silicon; no Apple firmware redistribution; GitHub arm64 runners use TCG emulation.
