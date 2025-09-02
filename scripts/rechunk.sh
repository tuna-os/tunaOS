#!/bin/bash

# A simple script to repartition an OCI image into equal-sized chunks.
# It takes a single argument: the URI of the container image to process.
#
# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# The rechunker OCI image to use for the process.
readonly RECHUNKER_IMAGE='ghcr.io/hhd-dev/rechunk:latest'

# --- Input Validation ---
if [ -z "$1" ]; then
	echo "Error: No container image URI provided." >&2
	echo "Usage: $0 <container_image_uri>"
	echo "Example: $0 quay.io/fedora/fedora-coreos:stable"
	exit 1
fi
readonly REF="$1"
readonly WORKSPACE=$(pwd)/.rechunk

# --- Cleanup previous runs ---
readonly OUT_NAME=$(echo "$REF" | rev | cut -d'/' -f1 | rev | sed 's/:/_/')
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
sudo podman pull oci:$WORKSPACE/$OUT_NAME
echo "✅ Image loaded into Podman as: $OUT_NAME"
echo "Cleaning up..."
if sudo podman inspect "$OUT_NAME" >/dev/null 2>&1; then
	rm -rf "$WORKSPACE/$OUT_NAME"
	sudo podman tag "$OUT_NAME" "$OUT_NAME:rechunked"
fi