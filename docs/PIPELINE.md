# TunaOS Build Pipeline Reference

How images and ISOs get built, verified, and published. If you change CI, read this first; if you change the pipeline's shape, update this file.

---

## The Build Matrix

`variant × desktop × hardware_layer`, defined in `.github/build-config.yml`.

| Variant | Base | Desktops | HWE/NVIDIA | Platforms |
|---------|------|----------|------------|-----------|
| yellowfin | AlmaLinux Kitten 10 | gnome, gnome50, cosmic, kde, niri, xfce | yes | amd64, amd64/v2, arm64 |
| albacore | AlmaLinux 10 | gnome, gnome50, cosmic, kde, niri, xfce | yes | amd64, amd64/v2, arm64 |
| skipjack | CentOS Stream 10 | gnome, gnome50, cosmic, kde, niri | gnome/cosmic families | amd64, arm64 |
| bonito | Fedora 44 | gnome, cosmic, kde, niri, xfce | nvidia only | amd64, arm64 |
| grouper | Ubuntu 26.04 | gnome, kde, niri, xfce | none | amd64 |

---

## Build Stages (DAG)

```
Stage 1:  base
             │
Stage 2:  ┌──┼──────────────────────────────────────┐
          │  base-hwe  base-nvidia                   │
          │  gnome  gnome50  kde  niri  cosmic  xfce │  (all parallel)
          └──┬───────────────────────────────────────┘
             │
Stage 3:  gnome-hwe, kde-hwe, niri-hwe, cosmic-hwe     (layer on DE image)
          gnome-nvidia, kde-nvidia, niri-nvidia, cosmic-nvidia
             │
Stage 4:  gnome-nvidia-hwe                              (layer on gnome-hwe)
```

**Key insight**: HWE/nvidia layers are applied ON TOP of DE images (not the other way around). `gnome-hwe` = `yellowfin:gnome` + HWE kernel. The DE is never duplicated.

---

## Workflow Files

| File | Role |
|------|------|
| `build-yellowfin.yml` / `build-albacore.yml` / etc. | Top-level per-variant entry points (trigger: schedule + manual) |
| `build-variant.yml` | Unified orchestrator — generates matrix, runs 4-stage DAG |
| `reusable-build-image.yml` | Per-platform build + push + sign + boot-gate |
| `reusable-build-artifacts.yml` | ISO/QCOW2 generation |

---

## How a Build Works

1. **Matrix generation** — `build-variant.yml` reads `build-config.yml`, emits per-stage matrices
2. **Stage 1** — builds `base` (Containerfile `base-no-de` target)
3. **Stage 2** — builds DE images via `install-desktop.sh <de>` (reads YAML manifests)
4. **Stage 3-4** — layers HWE/nvidia via `Containerfile.overlay`
5. **Rechunk** — chunkah produces ostree-optimized layers for delta updates
6. **Boot gate** — QEMU verifies the image boots (PR builds only)
7. **Publish** — multi-arch manifest pushed to GHCR, signed with cosign

---

## Flavor Resolution

`scripts/resolve-flavor.sh` maps any flavor to its build parameters:

```bash
$ ./scripts/resolve-flavor.sh yellowfin gnome-nvidia
CONTAINERFILE="Containerfile.overlay"
DESKTOP_FLAVOR="desktop"
ENABLE_HWE="0"
ENABLE_NVIDIA="1"
OVERLAY_TYPE="nvidia"
PARENT_FLAVOR="gnome"
```

---

## The Manifest Installer

DE packages are installed by `build_scripts/install-desktop.sh`, which reads `manifests/desktops/<de>.yaml`:

```yaml
# manifests/desktops/kde.yaml
display_manager: sddm
packages:
  fedora:
    groups: [kde-desktop]
    packages: [sddm, dolphin, konsole, ...]
  el10:
    groups: ["KDE Plasma Workspaces", ...]
    optional: [kdeconnect, nvtop, ...]
  apt:
    - kde-plasma-desktop
    - sddm
versionlock: [plasma-desktop, "qt6-*"]
```

Supports: dnf (Fedora/EL10), apt (Ubuntu/Debian), pacman (Arch/CachyOS).

---

## Image Refs and Pinning

Three sources of image metadata, consolidated via `scripts/resolve-image.sh`:

| Source | Contains |
|--------|----------|
| `.github/build-config.yml` | `base_image` per variant |
| `image-versions.yaml` | Digest pins for common/brew/zirconium + download versions |
| `registry-map.yaml` | Mirror overrides |

Usage: `./scripts/resolve-image.sh yellowfin common` → full `image@sha256:...` ref.

---

## Local Development

```bash
just build yellowfin gnome             # build locally
just qcow2 yellowfin gnome             # generate VM disk
just verify-disk ./yellowfin-gnome.qcow2  # QEMU boot check
just iso yellowfin gnome               # build ISO via tacklebox
```

---

## Renovate (Automated Updates)

All dependency updates automerge via `renovate.json`:
- Image digest pins (image-versions.yaml)
- GitHub Actions SHA pins
- Git submodules
- Download versions (uupd, kcm_ublue, tacklebox)

No human review required — CI is the gate.
