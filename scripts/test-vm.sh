#!/bin/bash
set -euo pipefail

# Usage: ./scripts/test-vm.sh <variant> <flavor>
# Example: ./scripts/test-vm.sh yellowfin base

if [ "$#" -ne 2 ]; then
	echo "Usage: $0 <variant> <flavor>"
	echo "Example: $0 yellowfin base"
	exit 1
fi

VARIANT="$1"
FLAVOR="$2"

# Determine Architecture
ARCH=$(uname -m)
if [ "$ARCH" == "arm64" ]; then
	LIMA_ARCH="aarch64"
else
	LIMA_ARCH="x86_64"
fi

# Construct Image Name
# Matches logic in build-bootc-diskimage.sh / Justfile
# Expected: <variant>[-<flavor>].qcow2
if [ "$FLAVOR" == "base" ]; then
	IMAGE_FILENAME="${VARIANT}.qcow2"
	VM_NAME="tuna-${VARIANT}"
else
	IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
	VM_NAME="tuna-${VARIANT}-${FLAVOR}"
fi

IMAGE_PATH="$(pwd)/${IMAGE_FILENAME}"

if [ ! -f "$IMAGE_PATH" ]; then
	echo "Error: Image not found at $IMAGE_PATH"
	echo "Please build the image first (e.g., 'just qcow2 $VARIANT $FLAVOR')"
	exit 1
fi

if ! command -v limactl &>/dev/null; then
	echo "Error: limactl is not installed."
	echo "Please install Lima (https://lima-vm.io/)"
	exit 1
fi

echo "--- Preparing Test VM ---"
echo "VM Name: $VM_NAME"
echo "Image: $IMAGE_PATH"
echo "Arch: $LIMA_ARCH"

# Cleanup existing VM
if limactl list -q | grep -q "^${VM_NAME}$"; then
	echo "Stopping and deleting existing VM: $VM_NAME"
	limactl stop -f "$VM_NAME" 2>/dev/null || true
	limactl delete "$VM_NAME"
fi

# Generate Config
TEMPLATE_FILE="tests/lima-template.yaml"
CONFIG_FILE="$(mktemp)"
cp "$TEMPLATE_FILE" "$CONFIG_FILE"

# Replace placeholders
# Use | as delimiter to handle paths with slashes
sed -i "s|__IMAGE_PATH__|$IMAGE_PATH|g" "$CONFIG_FILE"
sed -i "s|__ARCH__|$LIMA_ARCH|g" "$CONFIG_FILE"

echo "Starting VM..."
# Start the VM. We use --tty=false to avoid stealing the terminal if running via just
limactl start --name="$VM_NAME" --tty=false "$CONFIG_FILE"

echo "VM Started!"

# Get VNC Port
# Try strictly parsing the JSON stream (redirecting stderr to /dev/null to avoid WARN logs breaking jq)
VNC_DISPLAY=$(limactl list --json 2>/dev/null | jq -r "select(.name==\"$VM_NAME\") | .video.vnc.display")

# Fallback: check the vncdisplay file directly
if [ -z "$VNC_DISPLAY" ] || [ "$VNC_DISPLAY" == "null" ]; then
	VNC_FILE="$HOME/.lima/$VM_NAME/vncdisplay"
	if [ -f "$VNC_FILE" ]; then
		VNC_DISPLAY=$(cat "$VNC_FILE")
	fi
fi

if [ -n "$VNC_DISPLAY" ] && [ "$VNC_DISPLAY" != "null" ]; then
	echo "VNC listening at: $VNC_DISPLAY"

	# Handle the "127.0.0.1:0,to=9" format (extract everything before comma)
	VNC_DISPLAY=${VNC_DISPLAY%%,*}

	# Try to open VNC viewer
	if command -v xdg-open &>/dev/null; then
		echo "Opening Default VNC Viewer..."
		xdg-open "vnc://$VNC_DISPLAY" || echo "Failed to open VNC viewer automatically."
	elif command -v open &>/dev/null; then
		# macOS
		echo "Opening Screen Sharing..."
		open "vnc://$VNC_DISPLAY" || echo "Failed to open VNC viewer automatically."
	else
		echo "Could not detect tool to open VNC URI. Please connect manually to $VNC_DISPLAY"
	fi
else
	echo "Could not determine VNC display address."
fi

echo "---"
echo "To access shell: limactl shell $VM_NAME"
echo "To stop: limactl stop $VM_NAME"
