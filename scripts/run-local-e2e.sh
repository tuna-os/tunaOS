#!/usr/bin/bash
set -e

IMAGE_URI="$1"

if [ -z "$IMAGE_URI" ]; then
    echo "Usage: $0 <image_uri>"
    echo "Example: $0 ghcr.io/tuna-os/albacore:next"
    exit 1
fi

# Extract name for files
IMAGE_NAME=$(echo "$IMAGE_URI" | awk -F'/' '{print $NF}' | awk -F':' '{print $1}')
ISO_FILE="${IMAGE_NAME}.iso"

# 1. Build ISO if not exists
if [ ! -f "$ISO_FILE" ]; then
    echo "Building ISO image for $IMAGE_URI..."
    
    # Determine variant from image name
    VARIANT=$(echo "$IMAGE_NAME" | sed 's/-dx$//' | sed 's/-gdx$//')
    
    # Determine flavor
    if [[ "$IMAGE_NAME" == *"-gdx" ]]; then
        FLAVOR="gdx"
    elif [[ "$IMAGE_NAME" == *"-dx" ]]; then
        FLAVOR="dx"
    else
        FLAVOR="base"
    fi
    
    # Determine repo type
    if [[ "$IMAGE_URI" == ghcr.io/* ]]; then
        REPO="ghcr"
    else
        REPO="local"
    fi
    
    echo "Building ISO: variant=$VARIANT, flavor=$FLAVOR, repo=$REPO"
    
    # Build using titanoboa
    ./scripts/build-titanoboa.sh "$VARIANT" "$FLAVOR" "$REPO"
    
    # Find the built ISO and move it
    BUILD_DIR=".build/${VARIANT}-${FLAVOR}"
    BUILT_ISO=$(find "$BUILD_DIR" -name "*.iso" -type f | head -n 1)
    
    if [ -z "$BUILT_ISO" ]; then
        echo "ERROR: ISO not found after build!"
        exit 1
    fi
    
    # Move and rename
    mv "$BUILT_ISO" "$ISO_FILE"
    sudo chown $(id -u):$(id -g) "$ISO_FILE"
    echo "ISO created: $ISO_FILE"
else
    echo "Using existing $ISO_FILE"
fi

# Ensure we own the file so podman can relabel it (fix for SELinux/root ownership)
if [ -f "$ISO_FILE" ]; then
    sudo chown $(id -u):$(id -g) "$ISO_FILE"
fi

# 2. Build Test Runner
echo "Building Test Runner Container..."
podman build -t tunaos-e2e-runner -f tests/e2e/Containerfile tests/e2e

# 3. Create Network
NETWORK_NAME="tunaos-e2e-net"
podman network exists $NETWORK_NAME || podman network create $NETWORK_NAME

# 4. Start QEMU with ISO
echo "Starting QEMU with ISO..."
# Check for KVM
KVM_ARGS=""
if [ -e /dev/kvm ]; then
    KVM_ARGS="--device /dev/kvm"
fi

# Remove existing qemu container if any
podman rm -f tunaos-qemu 2>/dev/null || true

podman run -d --name tunaos-qemu \
    $KVM_ARGS \
    --network $NETWORK_NAME \
    -e CPU_CORES=4 \
    -e RAM_SIZE=8G \
    -e DISK_SIZE=64G \
    -v "$(pwd)/$ISO_FILE":/boot.iso:Z \
    ghcr.io/qemus/qemu

# Wait for QEMU to be ready (simple check)
echo "Waiting for QEMU to start..."
sleep 5

# 5. Run Test
echo "Running Selenium Test..."
podman run --rm \
    --network $NETWORK_NAME \
    -e VNC_URL="http://tunaos-qemu:8006" \
    -v "$(pwd)":/app/artifacts:Z \
    tunaos-e2e-runner

EXIT_CODE=$?

# 6. Cleanup
echo "Cleaning up..."
podman rm -f tunaos-qemu
# podman network rm $NETWORK_NAME # Optional, keep it for cache

if [ $EXIT_CODE -eq 0 ]; then
    echo "Test PASSED!"
else
    echo "Test FAILED!"
fi

exit $EXIT_CODE
