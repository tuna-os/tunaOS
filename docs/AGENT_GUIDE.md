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

The generic installer `build_scripts/install-desktop.sh` reads a manifest and installs the desktop. One script, all desktops, all OS families.

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/resolve-flavor.sh` | Routes flavor → Containerfile, target, parent, flags |
| `scripts/resolve-image.sh` | Resolves image refs (base, common, brew, akmods) |
| `scripts/build-image-inner.sh` | The build engine (env-var driven, replaces old Justfile monolith) |
| `build_scripts/install-desktop.sh` | Generic manifest-driven DE installer |
| `build_scripts/lib.sh` | Shared library (OS detection, pkg abstraction, retry logic) |
| `build_scripts/gnome-extensions.sh` | GNOME extension compilation (separate cache layer) |

### Containerfiles

| File | Purpose |
|------|---------|
| `Containerfile` | Main build — base stage + all DE stages |
| `Containerfile.overlay` | HWE/nvidia layer (parameterized by `OVERLAY_TYPE`) |
| `Containerfile.ubuntu` | Ubuntu/Debian bootcification |
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
| `bonito` | 🎣 | Fedora 44 | dnf | In progress |
| `grouper` | 🐟 | Ubuntu 26.04 | apt | Experimental |
| `redfin` | 🔒 | RHEL 10 | dnf | Local-only |
| `marlin` | 🐟 | Arch Linux | pacman | Planned |
| `wahoo` | 🐟 | CachyOS | pacman | Planned |
| `flounder` | 🐟 | Debian Trixie | apt | Planned |

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
