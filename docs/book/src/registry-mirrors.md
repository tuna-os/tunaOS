# Registry Mirror Configuration

TunaOS uses a centralized registry abstraction layer to decouple image references from hardcoded registry hostnames. This enables mirroring, air-gapped builds, and enterprise compliance without patching source files.

## How It Works

All container image references flow through a single mapping file: `registry-map.yaml` at the repo root.

```yaml
# registry-map.yaml (excerpt)
registries:
  ghcr: "ghcr.io"
  quay: "quay.io"
  docker: "docker.io"

images:
  common:
    registry: ghcr
    path: projectbluefin/common
    tag: latest
  almalinux-bootc:
    registry: quay
    path: almalinuxorg/almalinux-bootc
    tag: "10"
```

Build scripts source `scripts/_registry.sh` and call `registry_ref()`:

```bash
source scripts/_registry.sh
common_ref=$(registry_ref common)
# → ghcr.io/projectbluefin/common:latest
```

## Environment Variable Overrides

All registry hostnames and image references can be overridden at build time via environment variables. No file edits needed.

### Registry Overrides

Set `TUNA_REGISTRY_<key>` to redirect all images from a registry to a mirror:

```bash
# Redirect all ghcr.io pulls to a local mirror
export TUNA_REGISTRY_ghcr=registry-mirror.internal.example.com

# Redirect quay.io pulls to a pull-through cache
export TUNA_REGISTRY_quay=quay-cache.internal.example.com
```

Registry keys: `ghcr`, `quay`, `docker`.

### Image Path Overrides

Set `TUNA_IMAGE_PATH_<name>` to override a specific image's path:

```bash
# Use a forked common image
export TUNA_IMAGE_PATH_common=my-org/common-fork

# Override a hyphenated image name
# (hyphens → underscores in the env var name)
export TUNA_IMAGE_PATH_centos_bootc=my-org/custom-centos
```

### Image Tag Overrides

Set `TUNA_IMAGE_TAG_<name>` to pin or change a tag:

```bash
# Pin to a known-good version
export TUNA_IMAGE_TAG_common=gts-2026-05-01
export TUNA_IMAGE_TAG_brew=v1.2.3

# Hyphenated image names: use underscores in env var
export TUNA_IMAGE_TAG_almalinux_bootc=11
export TUNA_IMAGE_TAG_centos_bootc=stream11
```

### Precendence

Overrides are checked in order:
1. `TUNA_IMAGE_PATH_<name>` — full path override (highest)
2. `TUNA_IMAGE_TAG_<name>` — tag override
3. `TUNA_REGISTRY_<key>` — registry hostname override

Defaults in `registry-map.yaml` apply when no override is set.

> **Note on naming**: Bash variable names cannot contain hyphens. For image
> names like `almalinux-bootc` or `centos-bootc`, replace hyphens with
> underscores in environment variable names:
> `TUNA_IMAGE_TAG_almalinux_bootc`, `TUNA_IMAGE_PATH_centos_bootc`, etc.

## Available Image Names

| Name | Default Reference | Used For |
|------|------------------|----------|
| `common` | `ghcr.io/projectbluefin/common:latest` | Base OS packages, configs |
| `brew` | `ghcr.io/ublue-os/brew:latest` | Homebrew package manager layer |
| `akmods` | `ghcr.io/ublue-os` | Kernel module build base |
| `akmods-nvidia-open` | `ghcr.io/ublue-os/akmods-nvidia-open` | NVIDIA open kernel modules |
| `almalinux-bootc` | `quay.io/almalinuxorg/almalinux-bootc:10` | AlmaLinux bootc base (Yellowfin) |
| `almalinux-bootc-kitten` | `quay.io/almalinuxorg/almalinux-bootc:10-kitten` | AlmaLinux Kitten bootc base |
| `centos-bootc` | `quay.io/centos-bootc/centos-bootc:stream10` | CentOS Stream bootc base (Albacore) |
| `fedora-bootc` | `quay.io/fedora/fedora-bootc:44` | Fedora bootc base |
| `coreos-chunkah` | `quay.io/coreos/chunkah:latest` | ISO chunkah extraction tool |
| `novnc` | `ghcr.io/novnc/novnc:latest` | noVNC for Lima VM |
| `qemu` | `ghcr.io/qemus/qemu:latest` | QEMU for VM testing |
| `bluefin-iso` | `ghcr.io/hanthor/bluefin:lts` | Bluefin ISO bootc target |

## Usage Examples

### Scenario 1: Internal Mirror

Your organization mirrors all external images to an internal registry:

```bash
export TUNA_REGISTRY_ghcr=registry.corp.example.com
export TUNA_REGISTRY_quay=registry.corp.example.com
just build yellowfin gnome
```

All `ghcr.io/*` and `quay.io/*` pulls redirect to `registry.corp.example.com`.

### Scenario 2: Pull-Through Cache

You run a registry pull-through cache on `localhost:5000`:

```bash
export TUNA_REGISTRY_ghcr=localhost:5000
export TUNA_REGISTRY_quay=localhost:5000
```

### Scenario 3: CI with Mirror

GitHub Actions workflow using an Actions-level registry cache:

```yaml
env:
  TUNA_REGISTRY_ghcr: ${{ vars.REGISTRY_MIRROR || 'ghcr.io' }}
  TUNA_REGISTRY_quay: ${{ vars.REGISTRY_MIRROR || 'quay.io' }}
```

## Adding New Images

To register a new image, add an entry to `registry-map.yaml`:

```yaml
images:
  my-new-tool:
    registry: ghcr
    path: my-org/my-tool
    tag: v1.0
```

Then call `registry_ref my-new-tool` in your script. The env var override system works automatically: `TUNA_REGISTRY_ghcr`, `TUNA_IMAGE_PATH_my-new-tool`, `TUNA_IMAGE_TAG_my-new-tool`.
