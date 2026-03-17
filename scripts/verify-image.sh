#!/bin/bash
set -euo pipefail

# Usage: ./scripts/verify-image.sh <variant> <flavor>
# Example: ./scripts/verify-image.sh yellowfin base

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
if [ "$FLAVOR" == "base" ]; then
	IMAGE_FILENAME="${VARIANT}.qcow2"
	VM_NAME="verify-${VARIANT}"
else
	IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
	VM_NAME="verify-${VARIANT}-${FLAVOR}"
fi

# Sanitize VM_NAME for Lima
VM_NAME=$(echo "$VM_NAME" | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:]' '-' | sed 's/--/-/g' | sed 's/^-//;s/-$//')

IMAGE_PATH="$(pwd)/${IMAGE_FILENAME}"

if [ ! -f "$IMAGE_PATH" ]; then
	echo "Error: Image not found at $IMAGE_PATH"
	echo "Please build the image first (e.g., 'just qcow2 $VARIANT $FLAVOR')"
	exit 1
fi

if ! command -v limactl &>/dev/null; then
	echo "Error: limactl is not installed."
	exit 1
fi

echo "--- Verifying Image: $VARIANT:$FLAVOR ---"
echo "VM Name: $VM_NAME"

# Cleanup existing VM
if limactl list -q | grep -q "^${VM_NAME}$"; then
	limactl stop -f "$VM_NAME" 2>/dev/null || true
	limactl delete "$VM_NAME"
fi

# Create Lima Config
CONFIG_FILE="$(mktemp --suffix=.yaml)"
cat > "$CONFIG_FILE" <<LIMAEOF
vmType: qemu
arch: $LIMA_ARCH
cpus: 2
memory: 4GiB
disk: 20GiB

video:
  display: "vnc"

images:
  - location: "$IMAGE_PATH"
    arch: $LIMA_ARCH

mounts: []
ssh:
  localPort: 0
  loadDotSSHPubKeys: false
LIMAEOF

# Start VM
echo "Starting VM..."
limactl start --name="$VM_NAME" --tty=false "$CONFIG_FILE" --timeout=10m

# Verification Steps
echo "Waiting for Display Manager to become active..."
DM_SERVICE="gdm"
if [[ "$FLAVOR" == *"kde"* ]]; then
	DM_SERVICE="sddm"
elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then
	DM_SERVICE="greetd"
fi

echo "Checking service: $DM_SERVICE"

MAX_ATTEMPTS=30
for i in $(seq 1 $MAX_ATTEMPTS); do
	STATUS=$(limactl shell "$VM_NAME" -- systemctl is-active "$DM_SERVICE" 2>/dev/null || echo "inactive")
	echo "Attempt $i/$MAX_ATTEMPTS: $DM_SERVICE is $STATUS"
	if [[ "$STATUS" == "active" ]]; then
		break
	fi
	sleep 10
done

if [[ "$STATUS" != "active" ]]; then
	echo "ERROR: $DM_SERVICE failed to become active"
	limactl shell "$VM_NAME" -- journalctl -u "$DM_SERVICE" --no-pager -n 50 || true
	limactl stop -f "$VM_NAME" || true
	limactl delete "$VM_NAME"
	exit 1
fi

echo "Image Verification PASSED for $VARIANT:$FLAVOR"

# Cleanup
limactl stop -f "$VM_NAME"
limactl delete "$VM_NAME"
rm "$CONFIG_FILE"
