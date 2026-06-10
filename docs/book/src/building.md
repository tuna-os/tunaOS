# Building TunaOS

TunaOS images are built with **podman** and the **just** command runner using multi-stage Containerfiles.

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| [podman](https://podman.io) | 5.x | Container build engine (BuildKit) |
| [just](https://github.com/casey/just) | 1.x | Command runner |
| [yq](https://github.com/mikefarah/yq) | 4.x | YAML query tool for build config |
| [git](https://git-scm.com) | 2.x | Source control + submodules |

Optional for ISO builds:

| Tool | Purpose |
|------|---------|
| [tacklebox](https://github.com/tuna-os/tacklebox) | ISO generation (auto-downloaded if missing) |
| [lima](https://lima-vm.io) | VM-based image verification |
| [qemu-img](https://www.qemu.org) | QCOW2 conversion |

## Quick Start

```bash
# Clone the repo
git clone https://github.com/tuna-os/tunaOS.git
cd tunaOS

# Build Yellowfin with GNOME desktop
just build yellowfin gnome
```

This produces a local image tagged `localhost/yellowfin:gnome`.

## Build Variants and Flavors

### Syntax

```bash
just build <variant> <flavor>
```

### Variants

| Variant | Base OS | Notes |
|---------|---------|-------|
| `yellowfin` | AlmaLinux Kitten 10 | Closest to upstream CentOS Stream |
| `albacore` | AlmaLinux 10 | Stable, RHEL-compatible |
| `skipjack` | CentOS Stream 10 | Upstream of RHEL |
| `bonito` | Fedora 44 | Cutting-edge packages |
| `redfin` | RHEL 10 | Subscription required, local-build only |

### Flavors

| Flavor | Description |
|--------|-------------|
| `base` | No desktop environment |
| `gnome` | GNOME desktop |
| `gnome50` | GNOME 50 (latest) |
| `kde` | KDE Plasma |
| `cosmic` | COSMIC desktop |
| `niri` | Niri tiling compositor |
| `gnome-hwe` | GNOME with HWE kernel |
| `gnome-gdx` | GNOME with NVIDIA drivers |
| `gnome-gdx-hwe` | GNOME with NVIDIA on HWE kernel |

Any desktop flavor can be combined with `-hwe`, `-gdx`, or `-gdx-hwe` suffixes.

### Platform Selection

The build auto-detects your platform. Override with:

```bash
just build yellowfin gnome target_platform=linux/arm64
just build albacore kde target_platform=linux/amd64/v2
```

## Build Pipeline

Each build runs through these stages:

1. **Context assembly** — system files, brew files, and build scripts copied into a scratch image
2. **Base stage** (`base-no-de`) — copy files, install packages, configure services, cleanup
3. **Hardware variant stage** (optional) — `base-hwe` or `base-gdx` for chain builds
4. **DE stage** — install desktop packages (`gnome.sh`, `kde.sh`, etc.), versionlock glib2, symlink `/opt → /var/opt`
5. **Chunkah rechunking** — reduces image layer count for distribution efficiency
6. **Final stage** — apply labels and OCI annotations

### Containerfile Selection

The Justfile automatically selects the correct Containerfile:

| Flavor suffix | Containerfile | Description |
|---------------|---------------|-------------|
| *(none)* | `Containerfile` | Base build with `base-no-de` |
| `-hwe` | `Containerfile.hwe` | HWE kernel layer |
| `-gdx` | `Containerfile.gdx` | NVIDIA driver layer |
| `-gdx-hwe` | `Containerfile.gdx` | GDX on HWE parent |

## Building ISOs

### Via tacklebox (recommended)

```bash
# Build ISO for Yellowfin GNOME
just iso yellowfin gnome

# Build from GHCR images (no local build needed)
just iso yellowfin gnome repo=ghcr
```

This uses `scripts/build-iso-tacklebox.sh` which automatically downloads tacklebox if not installed.

### Building QCOW2 disk images

```bash
# Build QCOW2 for Lima/QEMU
just qcow2 yellowfin gnome
```

## Building for RHEL (Redfin)

Redfin requires a Red Hat subscription. See [Redfin Setup](../rhel-setup.md) for prerequisites. Then:

```bash
just build redfin base
just build redfin gnome
```

RHSM credentials are passed via BuildKit secrets — never stored in image layers.

## Using Build Cache

Local builds use a shared `.rpm-cache` volume for DNF package caching. The cache is:

- **Automatic** — enabled for local builds, disabled for CI
- **Shared** — all variants reuse the same cache
- **Persistent** — survives `just clean` (use `just clean-cache` to remove)

```bash
# Clean build artifacts, keep cache
just clean

# Remove cache too
just clean-cache
```

## Switching an Existing System

If you're running a bootc-based OS:

```bash
# Switch to TunaOS
sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
```

## Verification

### Test boot a QCOW2 image

```bash
# Build and boot in Lima VM with automated DM check
just test-vm yellowfin gnome

# Full demo: build QCOW2, start VM, open noVNC in browser
just demo albacore gnome
```

### Test boot an ISO

```bash
# Build and boot ISO in QEMU via web browser
just demo-iso skipjack gnome
```

### Verify image signatures

All published TunaOS images are signed with [cosign](https://github.com/sigstore/cosign) using keyless signing (OIDC). Verify any image before use:

```bash
# Verify with OIDC identity
cosign verify \
  --certificate-identity https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-image.yml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/tuna-os/yellowfin:gnome

# Verify with public key (from cosign.pub in the repo)
cosign verify --key cosign.pub ghcr.io/tuna-os/yellowfin:gnome
```

For local builds, images are not signed — verification applies only to published GHCR images.
