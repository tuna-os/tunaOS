#!/bin/bash

# A simple script to repartition an OCI image into equal-sized chunks.
# It takes a single argument: the URI of the container image to process.
#
# Strict mode: exit on error, unset variable, or pipeline middle failure.
set -euo pipefail

# Source registry resolution for mirror configurability (RFC-009).
# Falls back to hardcoded ref if _registry.sh is unavailable.
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/_registry.sh" ]]; then
	. "$(dirname "${BASH_SOURCE[0]}")/_registry.sh"
fi

# --- Configuration ---
# SECURITY: Pinned to a specific SHA256 digest to prevent supply-chain
# attacks via tag mutation. Resolved through registry_ref() for mirror
# configurability (RFC-009). To update the digest:
#   podman pull ghcr.io/hhd-dev/rechunk:latest
#   podman inspect ghcr.io/hhd-dev/rechunk:latest --format '{{.Digest}}'
readonly RECHUNKER_IMAGE="${RECHUNKER_IMAGE:-$(registry_ref rechunker 2>/dev/null || echo 'ghcr.io/hhd-dev/rechunk@sha256:8a84bd5a029681aa8db523f927b7c53b5aded9b078b81605ac0a2fedc969f528')}"

# --- Input Validation ---
if [ -z "$1" ]; then
	echo "Error: No container image URI provided." >&2
	echo "Usage: $0 <container_image_uri>"
	echo "Example: $0 quay.io/fedora/fedora-coreos:stable"
	exit 1
fi
readonly REF="$1"
WORKSPACE_TMP=$(pwd)/.rechunk
readonly WORKSPACE="$WORKSPACE_TMP"

# --- Cleanup previous runs ---
OUT_NAME_TMP=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
readonly OUT_NAME="$OUT_NAME_TMP"
sudo podman rmi "$OUT_NAME" || true
rm -rf "$WORKSPACE"
sudo podman image prune -f

echo "▶️  Starting rechunk process for image: $REF"

# --- Pull the image ---
sudo podman pull "$REF"

mkdir -p "$WORKSPACE"

## 1. Mount the source image
echo "---"
echo "⚙️  Mounting image..."
CREF=$(sudo podman create --platform linux/amd64 "$REF" bash)
MOUNT=$(sudo podman mount "$CREF")
echo "✅ Image mounted at: $MOUNT"

## 2. Create OSTree commit from the image
echo "---"
echo "⚙️  Creating OSTree commit..."

# Prune the filesystem tree
sudo podman run --rm \
	--privileged --security-opt label=disable \
	-v "$MOUNT":/var/tree \
	-e TREE=/var/tree \
	-u 0:0 \
	"$RECHUNKER_IMAGE" \
	/sources/rechunk/1_prune.sh

# Commit the tree to a temporary OSTree repository
sudo podman run --rm \
	--privileged --security-opt label=disable \
	-v "$MOUNT":/var/tree \
	-e TREE=/var/tree \
	-v "cache_ostree:/var/ostree" \
	-e REPO=/var/ostree/repo \
	-e RESET_TIMESTAMP=1 \
	-u 0:0 \
	"$RECHUNKER_IMAGE" \
	/sources/rechunk/2_create.sh

echo "Cleaning up original container and image..."
sudo podman unmount "$CREF"
echo "✅ OSTree commit created and source cleaned up."

## 3. Rechunk the commit into a new OCI image
echo "---"
echo "⚙️  Rechunking into new OCI image..."

# Run the final chunking script
sudo podman run --rm \
	--privileged --security-opt label=disable \
	-v "$WORKSPACE":/workspace \
	-v "cache_ostree:/var/ostree" \
	-e REPO=/var/ostree/repo \
	-e OUT_NAME="$OUT_NAME" \
	-e OUT_REF="oci:$OUT_NAME" \
	-e VERSION="$(date +'%y%m%d')" \
	-u 0:0 \
	"$RECHUNKER_IMAGE" \
	/sources/rechunk/3_chunk.sh

## 4. Finalize and Cleanup
echo "---"
echo "⚙️  Finalizing..."

# Set correct permissions on the output directory
echo "Setting permissions for output directory: $WORKSPACE/$OUT_NAME"
sudo chown -R "$(id -u):$(id -g)" "$WORKSPACE/$OUT_NAME"

# Remove the temporary OSTree volume
echo "Removing temporary OSTree volume..."
sudo podman volume rm cache_ostree >/dev/null

echo "---"
echo "✅ Success! Rechunking complete."
echo "📦 The new OCI image is located at: $WORKSPACE/./$OUT_NAME"

# podman import OCI image

echo "loading into podman..."
sudo podman pull oci:"$WORKSPACE"/"$OUT_NAME"
echo "✅ Image loaded into Podman as: $OUT_NAME"
echo "Cleaning up..."
if sudo podman inspect "$OUT_NAME" >/dev/null 2>&1; then
	rm -rf "${WORKSPACE:?}/$OUT_NAME"
	sudo podman tag "$OUT_NAME" "$OUT_NAME:rechunked"
fi
