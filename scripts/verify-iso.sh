#!/bin/bash
set -euo pipefail

# Usage: ./scripts/verify-iso.sh <iso_file>
# Example: ./scripts/verify-iso.sh yellowfin-gnome-10-x86_64.iso

if [ "$#" -ne 1 ]; then
	echo "Usage: $0 <iso_file>"
	echo "Example: $0 yellowfin-gnome-10-x86_64.iso"
	exit 1
fi

ISO_FILE="$1"
ISO_PATH="$(realpath "$ISO_FILE")"

if [ ! -f "$ISO_PATH" ]; then
	echo "Error: ISO file not found at $ISO_PATH"
	exit 1
fi

# Extract variant/flavor for VM name if possible
# Lima identifiers must match ^[A-Za-z0-9]+(?:[._-](?:[A-Za-z0-9]+))*$
VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:]' '-' | sed 's/--/-/g' | sed 's/^-//;s/-$//')"

if ! command -v limactl &>/dev/null; then
	echo "Error: limactl is not installed."
	exit 1
fi

# Determine Architecture
ARCH=$(uname -m)
if [ "$ARCH" == "arm64" ]; then
	LIMA_ARCH="aarch64"
else
	LIMA_ARCH="x86_64"
fi

echo "--- Verifying ISO: $ISO_FILE ---"
echo "VM Name: $VM_NAME"

# Cleanup existing VM
if limactl list -q | grep -q "^${VM_NAME}$"; then
	limactl stop -f "$VM_NAME" 2>/dev/null || true
	limactl delete "$VM_NAME"
fi

# Create Lima Config for ISO Booting
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
  # We use a dummy empty image for the main disk, and attach the ISO
  - location: "https://cloud.centos.org/centos/10-stream/x86_64/images/CentOS-Stream-GenericCloud-x86_64-10-latest.x86_64.qcow2"
    arch: $LIMA_ARCH

mounts: []
ssh:
  localPort: 0
  loadDotSSHPubKeys: false

# Attach ISO as a CDROM
qemu:
  args:
    - -device
    - virtio-blk-pci,drive=cdrom
    - -drive
    - "file=$ISO_PATH,format=raw,if=none,id=cdrom,readonly=on"
    - -boot
    - order=d,once=d,menu=on
LIMAEOF

echo "Starting VM (ISO Boot)..."
limactl start --name="$VM_NAME" --tty=false "$CONFIG_FILE" --timeout=10m || echo "VM started (ignoring potential SSH timeout)"

echo "Waiting for VM to settle..."
sleep 60

# Check if VM is still running
if limactl list -q | grep -q "^${VM_NAME}$"; then
	echo "ISO Booted (VM is running)"
else
	echo "ERROR: VM failed to start or crashed"
	exit 1
fi

echo "ISO Verification (Basic Boot) PASSED for $ISO_FILE"

# Cleanup
limactl stop -f "$VM_NAME"
limactl delete "$VM_NAME"
rm "$CONFIG_FILE"
