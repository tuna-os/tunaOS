#!/bin/bash
set -euo pipefail

# Check if running with root privileges
if [ "$EUID" -ne 0 ]; then
    echo "Elevating privileges with sudo..."
    # Copy to /tmp to avoid noexec home partition issues if present
    TMP_SCRIPT=$(mktemp /tmp/build-live-iso.XXXXXX.sh)
    cp "$0" "$TMP_SCRIPT"
    chmod +x "$TMP_SCRIPT"
    # Capture current directory to pass it along
    CUR_DIR=$(pwd)
    exec sudo "$TMP_SCRIPT" "$@" "$CUR_DIR"
fi

# If we were called with an extra argument, it's the original directory
if [ "$#" -gt 4 ]; then
    ORIG_DIR="${!#}"
    cd "$ORIG_DIR"
fi

# Determine script and project root
# BASH_SOURCE[0] might be the /tmp script
REAL_SCRIPT_PATH=$(realpath "${BASH_SOURCE[0]}")
# If we are in /tmp, we can't easily find PROJECT_ROOT from it unless we pass it.
# Let's assume the user is running from project root or we passed it.
PROJECT_ROOT=$(pwd)
# Ensure we are in project root (where live-iso/ directory is)
if [ ! -d "live-iso" ]; then
    echo "Error: Must run from project root (live-iso directory not found in $(pwd))"
    exit 1
fi

# Script to build live ISOs using bootc-isos (Ondrej Budai) logic.
# Usage: ./build-live-iso.sh <variant> <flavor> <repo> [tag]

VARIANT="${1:-yellowfin}"
FLAVOR="${2:-gnome}"
REPO="${3:-local}"
TAG="${4:-latest}"
TYPE="${5:-iso}"

case "$VARIANT" in
"yellowfin") LABEL="Yellowfin-Live" ;;
"albacore") LABEL="Albacore-Live" ;;
"skipjack") LABEL="Skipjack-Live" ;;
"bonito") LABEL="Bonito-Live" ;;
*) LABEL="TunaOS-Live" ;;
esac

# Construct the image URI
# In TunaOS, local builds use variant:flavor as the tag if tag=latest
IMAGE_TAG="${TAG}"
if [ "$IMAGE_TAG" = "latest" ]; then
    IMAGE_TAG="${FLAVOR}"
fi

# Define common IMAGE_NAME for installer and output naming
if [ "$FLAVOR" != "base" ] && [ "$FLAVOR" != "gnome" ]; then
    IMAGE_NAME="${VARIANT}-${FLAVOR}"
else
    IMAGE_NAME="${VARIANT}"
fi

if [ "$REPO" = "ghcr" ]; then
    GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
    BASE_IMAGE="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${IMAGE_NAME}:${TAG}"
elif [ "$REPO" = "local" ]; then
    # Local uses variant:flavor
    BASE_IMAGE="localhost/${VARIANT}:${IMAGE_TAG}"
    # If not running as root, we might need to push the image to the root store
    # but since we are re-execing as root, we should check if root podman has it.
    if ! podman image exists "$BASE_IMAGE"; then
        echo "==> Image $BASE_IMAGE not found in root storage. Attempting to pull from user storage..."
        # This is tricky because root podman can't easily see user podman images.
        # We can use 'podman save' and 'podman load' if it's really local only.
        # But if it was just built with 'just build', it's in user storage.
        # For simplicity, we'll try to pull it if it looks like a registry ref,
        # but for localhost/ we'll try to find a way.
        
        # In a typical dev environment, the user would have to build it as root
        # or we'd have to export/import it.
        # Let's try to export/import if it's localhost/
        USER_ID=$(logname)
        echo "==> Exporting $BASE_IMAGE from user $USER_ID and importing to root..."
        sudo -u "$USER_ID" podman save "$BASE_IMAGE" | podman load
    fi
else
    echo "Unknown repo: $REPO. Use 'local' or 'ghcr'" >&2
    exit 1
fi
INSTALLER_IMAGE="localhost/${IMAGE_NAME}-live-installer"
OUTPUT_DIR="$(pwd)/.build/live-iso/${VARIANT}-${FLAVOR}"
mkdir -p "$OUTPUT_DIR"

echo "==> Building live installer image: $INSTALLER_IMAGE from $BASE_IMAGE"
podman build \
	--cap-add sys_admin \
	--security-opt label=disable \
	--build-arg "BASE_IMAGE=${BASE_IMAGE}" \
	--build-arg "LABEL=${LABEL}" \
	--build-arg "DESKTOP_FLAVOR=${FLAVOR}" \
	-t "$INSTALLER_IMAGE" \
	-f live-iso/common/Containerfile \
	live-iso/common

echo "==> Generating live ISO using official bootc-image-builder..."
podman run --rm --privileged \
    -v /var/lib/containers/storage:/var/lib/containers/storage \
    -v "${OUTPUT_DIR}":/output:Z \
    quay.io/centos-bootc/bootc-image-builder:latest \
    build --output /output \
    --type "$TYPE" \
    --use-librepo \
    "$INSTALLER_IMAGE"

# The output ISO is usually named something like 'bootc-generic-iso.iso' or similar.
# Ondrej's tool seems to output it to the output directory.
# Let's find it and rename it.
ISO_FILE=$(find "$OUTPUT_DIR" -name "*.iso" | head -n 1)
if [ -n "$ISO_FILE" ]; then
	FINAL_ISO="${VARIANT}-${FLAVOR}-live.iso"
	mv "$ISO_FILE" "./${FINAL_ISO}"
	echo "==> Success! Live ISO created: ${FINAL_ISO}"

	# Optional R2 upload
	if [[ "${UPLOAD_R2:-false}" == "true" ]]; then
		echo "==> Uploading to Cloudflare R2..."
		# We assume rclone is configured as R2
		rclone copy --log-level INFO --checksum --s3-no-check-bucket "./${FINAL_ISO}" R2:tunaos/live-isos/
		echo "==> Uploaded: ${FINAL_ISO}"
	fi
else
	echo "==> Error: ISO file not found in $OUTPUT_DIR"
	exit 1
fi
