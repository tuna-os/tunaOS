# TunaOS Build Pipeline Reference

How images and ISOs get built, verified, and published. If you change CI, read this first; if you change the pipeline's shape, update this file.

---

## The Build Matrix

`variant × desktop × hardware_layer`, defined in `.github/build-config.yml`.

Shell entrypoints resolve that contract through
`scripts/lib/build-config.sh`. For tests that use an alternate contract, set
`TUNAOS_BUILD_CONFIG`. Do not add new runtime dependencies on the current
`.github/` storage path.

| Variant | Base | Desktops | HWE/NVIDIA | Platforms |
|---------|------|----------|------------|-----------|
| yellowfin | AlmaLinux Kitten 10 | gnome, cosmic, kde, niri, xfce | yes | amd64, amd64/v2, arm64 |
| albacore | AlmaLinux 10 | gnome, cosmic, kde, niri, xfce | yes | amd64, amd64/v2, arm64 |
| skipjack | CentOS Stream 10 | gnome, cosmic, kde, niri | gnome/cosmic families | amd64, arm64 |
| bonito | Fedora 44 | gnome, cosmic, kde, niri, xfce | nvidia only | amd64, arm64 |
| grouper | Ubuntu 26.04 | gnome, kde, niri, xfce | none | amd64 |

---

## Build Stages (DAG)

```
Stage 1:  base
             │
Stage 2:  ┌──┼──────────────────────────────────────┐
          │  base-hwe  base-nvidia                   │
          │  gnome  kde  niri  cosmic  xfce │  (all parallel)
          └──┬───────────────────────────────────────┘
             │
Stage 3:  gnome-hwe, kde-hwe, niri-hwe, cosmic-hwe     (layer on DE image)
          gnome-nvidia, kde-nvidia, niri-nvidia, cosmic-nvidia
             │
Stage 4:  gnome-nvidia-hwe                              (layer on gnome-hwe)
```

**Key insight**: the overlay stage applies HWE/nvidia layers ON TOP of DE images (not the other way around). `gnome-hwe` = `yellowfin:gnome` + HWE kernel. The DE is never duplicated.

---

## Workflow Files

| File | Role |
|------|------|
| `build-yellowfin.yml` / `build-albacore.yml` / etc. | Top-level per-variant entry points (trigger: schedule + manual) |
| `build-variant.yml` | Unified orchestrator — generates matrix, runs 4-stage DAG |
| `reusable-build-image.yml` | Per-platform build + push + sign + boot-gate (Decomposition Plan: [docs/architecture/reusable-build-image-decomposition.md](architecture/reusable-build-image-decomposition.md)) |
| `reusable-build-artifacts.yml` | ISO/QCOW2 generation |

---

## How a Build Works

1. **Matrix generation** — `build-variant.yml` reads `build-config.yml`, emits per-stage matrices
2. **Stage 1** — builds `base` (Containerfile `base-no-de` target)
3. **Stage 2** — builds DE images via `install-desktop.sh <de>` (reads YAML manifests)
4. **Stage 3-4** — layers HWE/nvidia via `Containerfile.overlay`
5. **Rechunk** — chunkah makes ostree-optimized layers for delta updates. The relabel stage writes `/usr/share/tunaos/build-info.json` with image provenance. This prevents an empty filesystem layer.
6. **Artifact check** — the check runs on zstd layers under 50 bytes after decompression. It accepts tar entries with content and rejects tar layers that are empty.
7. **Boot gate** — Corral boots the `-testing` image under QEMU, and Promote waits for the result (see [Boot gates](#boot-gates))
8. **Publish** — multi-arch manifest pushed to GHCR, signed with cosign

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

DE packages are installed by `build_scripts/desktop/install-desktop.sh`, which reads `manifests/desktops/<de>.yaml`:

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

## Tooling

### Boot gates

Corral runs the boot gate. `scripts/corral-boot-gate.sh` gives the image to `corral vmtest`. Corral installs the image to a disk and boots the disk under QEMU with UEFI. The script then reads the contract markers on the serial console. The Gate job in `reusable-build-image.yml` and the PR gate step use this script. The CI contract declares the PR gate in `.github/green-criteria.yml`.

The verdict is the same as the verdict of `scripts/iso-e2e.sh --disk`:

- **Pass:** `TUNAOS_DESKTOP_CONTRACT_OK` is on the console. Also, `TUNAOS_BASE_CONTRACT_FAIL` does not occur in the next 120 seconds.
- **Fail:** a contract `FAIL` marker, an emergency shell, or a kernel panic is on the console. Corral stops the wait when one of these occurs.
- **Fail:** no marker occurs before the timeout.

The disk agrees with `just qcow2`. A sealed image gets ext4, and other images get xfs. `TUNAOS_QCOW2_FILESYSTEM` overrides this choice. The kernel arguments are the same, and the boot entry also gets `tunaos.countme=0`. Thus a gate guest never sends an adoption report, from the first boot.

`image-versions.yaml` pins the Corral commit in `downloads.corral`, and `scripts/install-corral.sh` builds that commit. The workflow `corral-boot-gate.yml` boots one ostree image and one composefs image through the script when a pull request changes the script.

The GPU-routed compositors (cosmic, niri, xfwl4) use `just qcow2` and `scripts/iso-e2e.sh --disk`, because Corral has no virgl display. The Gate does not schedule these flavors at this time.

For a KubeVirt cluster, `scripts/boot-gate.sh` checks for `--karg` support in both fresh and resumed guests. It passes `tunaos.countme=0` before boot, or exits 77 before it creates a guest. See the [measured cause and test](ci-troubleshooting.md#automated-corral-guests-could-enter-adoption-counts).

---

## Renovate (Automated Updates)

`renovate.json` extends the shared `tuna-os/.github` policy and tracks:

- image digest pins (`image-versions.yaml`)
- SHA pins of GitHub Actions
- Git submodules
- pinned download versions

Routine minor, patch, pin, and digest updates may automerge only after required
CI and branch protection pass. Major updates and repository-specific holds
require human review. The config gate runs both Renovate's schema validator
and `scripts/check-renovate-automerge-policy.py`, because schema-valid rules
can still violate the org automerge boundary. See
[DEPENDENCY-FRESHNESS.md](DEPENDENCY-FRESHNESS.md) for the org policy,
Dependabot coordination, and monthly health check.
