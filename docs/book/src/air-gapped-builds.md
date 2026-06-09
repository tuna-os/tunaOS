# Air-Gapped Builds

Building TunaOS in an environment without internet access requires pre-staging all container images in a local registry and configuring the registry mirror overrides.

## Prerequisites

- A local container registry (e.g., distribution/distribution, Harbor, Quay)
- A staging host with internet access to preload images
- `podman` with access to the local registry
- The TunaOS repository fully cloned

## Step 1: Set Up a Local Registry

On a host within the air-gapped network, start a local registry:

```bash
podman run -d --name registry \
  -p 5000:5000 \
  -v registry-data:/var/lib/registry \
  docker.io/library/registry:2
```

Verify it's reachable:

```bash
curl http://localhost:5000/v2/_catalog
# → {"repositories":[]}
```

## Step 2: Preload Images

On a staging host with internet access, pull and push all required images to a tarball or directly to the local registry.

### Method A: Push to Local Registry (Recommended)

Use the registry map to enumerate all images:

```bash
# Install yq (YAML processor) if needed: pip install yq
source scripts/_registry.sh

# Pull all images and re-tag for local registry
for img in common brew akmods akmods-nvidia-open \
           almalinux-bootc centos-bootc fedora-bootc \
           coreos-chunkah novnc qemu bluefin-iso; do
    ref=$(registry_ref "$img")
    echo "Mirroring: $ref"
    podman pull "$ref"
    podman tag "$ref" "localhost:5000/${ref#*/}"
    podman push "localhost:5000/${ref#*/}"
done
```

### Method B: Export/Import Tarball

If the staging host cannot reach the air-gapped network directly:

```bash
# On staging host
source scripts/_registry.sh
mkdir -p image-exports
for img in common brew akmods akmods-nvidia-open \
           almalinux-bootc centos-bootc fedora-bootc \
           coreos-chunkah novnc qemu bluefin-iso; do
    ref=$(registry_ref "$img")
    podman pull "$ref"
    safe_name=$(echo "$ref" | tr '/:' '_')
    podman save "$ref" -o "image-exports/${safe_name}.tar"
done
tar czf tunaos-images.tar.gz image-exports/

# Transfer tunaos-images.tar.gz to air-gapped host via USB/SNEAKERNET

# On air-gapped host
tar xzf tunaos-images.tar.gz
for tar_file in image-exports/*.tar; do
    podman load -i "$tar_file"
    # Re-tag and push to local registry...
done
```

## Step 3: Configure Registry Overrides

Redirect all image pulls to the local registry:

```bash
export TUNA_REGISTRY_ghcr=localhost:5000
export TUNA_REGISTRY_quay=localhost:5000
export TUNA_REGISTRY_docker=localhost:5000
```

Or persistently in your shell profile or `.env` file:

```bash
# .env.local
TUNA_REGISTRY_ghcr=registry.airgap.internal:5000
TUNA_REGISTRY_quay=registry.airgap.internal:5000
TUNA_REGISTRY_docker=registry.airgap.internal:5000
```

## Step 4: Build

Run the build as normal. All image references resolve to the local registry:

```bash
source .env.local
just build yellowfin gnome
```

The build logs will show pulls from `localhost:5000` (or your configured registry) instead of `ghcr.io` / `quay.io`.

## Step 5: Verify Resolution

Confirm resolution is correct before a full build:

```bash
source scripts/_registry.sh
source .env.local

echo "Common: $(registry_ref common)"
echo "Brew:   $(registry_ref brew)"
echo "Base:   $(registry_ref almalinux-bootc)"
```

Expected output (with localhost:5000 override):

```
Common: localhost:5000/projectbluefin/common:latest
Brew:   localhost:5000/ublue-os/brew:latest
Base:   localhost:5000/almalinuxorg/almalinux-bootc:10
```

## Troubleshooting

### Image Not Found in Local Registry

Ensure all images were pushed. List registry contents:

```bash
curl http://localhost:5000/v2/_catalog
```

### Registry Requires Authentication

Set podman login for the local registry:

```bash
podman login localhost:5000
```

### Build Fails with "manifest unknown"

The image tag in the local registry doesn't match what `registry-map.yaml` expects. Check that you mirrored the correct tag:

```bash
# What the build expects:
registry_ref common
# → localhost:5000/projectbluefin/common:latest

# What's in the registry:
podman image ls localhost:5000/projectbluefin/common
```

### Adding Custom Images

If your build uses custom images not in `registry-map.yaml`, add them:

```yaml
# registry-map.yaml
images:
  custom-tool:
    registry: ghcr
    path: my-org/custom-tool
    tag: v2.1
```

Then preload the image and the override system handles the rest.
