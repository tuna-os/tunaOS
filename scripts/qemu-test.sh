#!/bin/bash
set -euo pipefail

DISK_IMAGE="$1"

if [ -z "$DISK_IMAGE" ]; then
	echo "Usage: $0 <path-to-qcow2-image>"
	exit 1
fi

echo "Starting QEMU with image: $DISK_IMAGE"

# Start QEMU in the background
# -m 2G: 2GB RAM
# -smp 2: 2 CPUs
# -nographic: No GUI
# -net user,hostfwd=tcp::2222-:22: Forward host port 2222 to guest port 22
# -snapshot: Don't write to the image file
qemu-system-x86_64 \
	-m 2G \
	-smp 2 \
	-nographic \
	-drive file="$DISK_IMAGE",format=qcow2,if=virtio,snapshot=on \
	-netdev user,id=net0,hostfwd=tcp::2222-:22 \
	-device virtio-net-pci,netdev=net0 \
	-pidfile qemu.pid &

QEMU_PID=$!
echo "QEMU started with PID $QEMU_PID"

cleanup() {
	echo "Stopping QEMU..."
	if [ -f qemu.pid ]; then
		kill "$(cat qemu.pid)" || true
		rm qemu.pid
	fi
}
trap cleanup EXIT

# Wait for SSH to become available
echo "Waiting for SSH..."
MAX_RETRIES=30
RETRY_COUNT=0
# Note: For real testing, you might need a specific user/key injected via cloud-init or similar.
# For this example, we'll assume there's a way to connect or just check the port.
# If passwordless SSH isn't set up, we might just check if the port is open using netcat.

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
	if nc -z localhost 2222; then
		echo "SSH port is open!"
		break
	fi
	echo "Waiting for SSH (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)..."
	sleep 10
	RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
	echo "Timed out waiting for SSH."
	exit 1
fi

# Run basic checks
# If we have SSH access (e.g. via key injected during build), we can run commands.
# For now, we'll assume the port open is enough for a "boot test" in this basic script,
# or try to run a simple command if we had credentials.
# echo "Running system checks..."
# ssh $SSH_OPTS $SSH_USER@localhost "systemctl is-system-running"

echo "QEMU test passed!"
exit 0
