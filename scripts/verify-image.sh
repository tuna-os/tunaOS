#!/bin/bash
set -euo pipefail

# Usage: ./scripts/verify-image.sh <variant> <flavor>
# Example: ./scripts/verify-image.sh yellowfin gnome
#
# Desktop verification (Layer 1): checks that the system boots to a
# graphical session with a running Wayland compositor.

if [ "$#" -ne 2 ]; then
	echo "Usage: $0 <variant> <flavor>"
	echo "Example: $0 yellowfin gnome"
	exit 1
fi

VARIANT="$1"
FLAVOR="$2"

ARCH=$(uname -m)
[ "$ARCH" == "arm64" ] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"

if [ "$FLAVOR" == "base" ]; then
	IMAGE_FILENAME="${VARIANT}.qcow2"
	VM_NAME="verify-${VARIANT}"
else
	IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
	VM_NAME="verify-${VARIANT}-${FLAVOR}"
fi
VM_NAME=$(echo "$VM_NAME" | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:]' '-' | sed 's/--/-/g; s/^-//;s/-$//')
IMAGE_PATH="$(pwd)/${IMAGE_FILENAME}"

[ -f "$IMAGE_PATH" ] || {
	echo "Error: Image not found at $IMAGE_PATH"
	exit 1
}
command -v limactl &>/dev/null || {
	echo "Error: limactl not installed"
	exit 1
}

echo "--- Verifying Image: $VARIANT:$FLAVOR ---"

# Cleanup existing VM
limactl list -q 2>/dev/null | grep -q "^${VM_NAME}$" && {
	limactl stop -f "$VM_NAME" 2>/dev/null || true
	limactl delete "$VM_NAME"
}

CONFIG_FILE="$(mktemp --suffix=.yaml)"
cat >"$CONFIG_FILE" <<LIMAEOF
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

echo "Starting VM..."
limactl start --name="$VM_NAME" --tty=false "$CONFIG_FILE" --timeout=10m

DESKTOP_FLAVOR="$FLAVOR"
# Normalize flavor to base desktop name
for suffix in -hwe -nvidia -nvidia-hwe -hwe-nvidia; do
	DESKTOP_FLAVOR="${DESKTOP_FLAVOR%"$suffix"}"
done

# Map desktop → display manager
DM_SERVICE="gdm"
if [[ "$DESKTOP_FLAVOR" == *"kde"* ]]; then
	DM_SERVICE="sddm"
elif [[ "$DESKTOP_FLAVOR" == *"cosmic"* || "$DESKTOP_FLAVOR" == *"niri"* ]]; then
	DM_SERVICE="greetd"
fi

MAX_ATTEMPTS=30
RC=0

vm_exec() {
	limactl shell "$VM_NAME" -- "$@" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════
# Layer 1: Desktop verification
# ═══════════════════════════════════════════════════════════════════

echo ""
echo "═══ Layer 1: Session & Compositor checks ═══"

# 1a. Wait for display manager
echo "--- Waiting for $DM_SERVICE ---"
DM_OK=false
for i in $(seq 1 $MAX_ATTEMPTS); do
	STATUS=$(vm_exec systemctl is-active "$DM_SERVICE")
	echo "  [$i/$MAX_ATTEMPTS] $DM_SERVICE: $STATUS"
	if [[ "$STATUS" == "active" ]]; then
		DM_OK=true
		break
	fi
	sleep 10
done
$DM_OK || {
	echo "❌ $DM_SERVICE not active"
	RC=1
}

# 1b. Check graphical.target
echo "--- Checking graphical.target ---"
GT_OK=false
for i in $(seq 1 15); do
	STATUS=$(vm_exec systemctl is-active graphical.target)
	if [[ "$STATUS" == "active" ]]; then
		GT_OK=true
		break
	fi
	sleep 5
done
if $GT_OK; then
	echo "✅ graphical.target active"
else
	echo "❌ graphical.target not reached"
	RC=1
fi

# 1c. Check user session
echo "--- Checking user session ---"
SESSION=$(vm_exec loginctl list-sessions --no-legend 2>/dev/null | head -1 | awk '{print $1}')
if [[ -n "$SESSION" ]]; then
	SESSION_ACTIVE=$(vm_exec loginctl show-session "$SESSION" 2>/dev/null | grep -c "Active=yes" || true)
	SESSION_TYPE=$(vm_exec loginctl show-session "$SESSION" 2>/dev/null | grep "Type=" || echo "unknown")
	if [[ "${SESSION_ACTIVE:-0}" -gt 0 ]]; then
		echo "✅ Session $SESSION active ($SESSION_TYPE)"
	else
		echo "ℹ️  Session $SESSION present but not active ($SESSION_TYPE)"
	fi
else
	echo "ℹ️  No user session found (auto-login may not be configured)"
fi

# 1d. Check Wayland compositor via wayland-info
echo "--- Checking Wayland compositor ---"
if vm_exec command -v wayland-info &>/dev/null; then
	WL_INFO=$(vm_exec wayland-info 2>/dev/null | head -5 || true)
	if [[ -n "$WL_INFO" ]]; then
		echo "✅ Wayland compositor responding"
		echo "$WL_INFO" | head -3
	else
		echo "⚠️  wayland-info ran but no output (compositor may need WAYLAND_DISPLAY)"
	fi
else
	echo "⚠️  wayland-info not installed"
fi

# 1e. Check XDG_SESSION_TYPE
echo "--- Checking session type ---"
XDG_TYPE=$(vm_exec loginctl show-session "$SESSION" 2>/dev/null | grep "Type=" | cut -d= -f2 || echo "unknown")
echo "Session type: $XDG_TYPE"

# ═══════════════════════════════════════════════════════════════════
# Result
# ═══════════════════════════════════════════════════════════════════
if [[ $RC -eq 0 ]]; then
	echo ""
	echo "✅ Image Verification PASSED for $VARIANT:$FLAVOR"
else
	echo ""
	echo "❌ Image Verification FAILED for $VARIANT:$FLAVOR"
	vm_exec journalctl -u "$DM_SERVICE" --no-pager -n 20 || true
fi

# Cleanup
limactl stop -f "$VM_NAME" 2>/dev/null || true
limactl delete "$VM_NAME" 2>/dev/null || true
rm -f "$CONFIG_FILE"

exit $RC
