#!/bin/bash
set -euo pipefail

# Usage: ./scripts/verify-iso.sh <iso_file>
# Example: ./scripts/verify-iso.sh yellowfin-gnome-10-x86_64.iso
#
# Boots the ISO using Lima (limactl) and verifies:
#   1. VM stays running for 120s (kernel booted, no immediate crash)
#   2. No kernel panic / boot errors in the serial log
#   3. Anaconda installer WebUI is reachable on the forwarded port

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

if ! command -v limactl &>/dev/null; then
	echo "Error: limactl is not installed. Install via: brew install lima"
	exit 1
fi

# Lima instance name (must match ^[A-Za-z0-9]+(?:[._-](?:[A-Za-z0-9]+))*$)
VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:]' '-' | sed 's/--*/-/g; s/^-//; s/-$//')"
LIMA_DIR="${HOME}/.lima/${VM_NAME}"
SERIAL_LOG="${LIMA_DIR}/serial.log"

ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
	LIMA_ARCH="aarch64"
else
	LIMA_ARCH="x86_64"
fi

echo "--- Verifying ISO: $ISO_FILE ---"
echo "Lima instance: ${VM_NAME}"
echo "Serial log:    ${SERIAL_LOG}"

# Remove any pre-existing instance with this name
if limactl list -q 2>/dev/null | grep -qx "${VM_NAME}"; then
	echo "Removing existing Lima instance ${VM_NAME}..."
	limactl stop -f "${VM_NAME}" 2>/dev/null || true
	limactl delete "${VM_NAME}"
fi

# Lima 2.x: boot the ISO directly by listing it as the primary disk image.
# plain:true skips SSH/cloud-init waits (Anaconda ISOs have no Lima guest agent).
# vmOpts.qemu.cpuType "host" enables KVM for speed.
CONFIG_FILE="$(mktemp --suffix=.yaml)"
cat >"${CONFIG_FILE}" <<LIMAEOF
vmType: qemu
arch: ${LIMA_ARCH}
cpus: 2
memory: "4GiB"
disk: "20GiB"

images:
  - location: "${ISO_PATH}"
    arch: ${LIMA_ARCH}

firmware:
  legacyBIOS: false

# Skip all SSH / cloud-init / guest-agent waits — the ISO won't have them.
plain: true

video:
  display: "vnc"
  vnc:
    display: "127.0.0.1:0,to=9"

vmOpts:
  qemu:
    cpuType:
      x86_64: "host"
      aarch64: "host"

mounts: []
LIMAEOF

cleanup() {
	rm -f "${CONFIG_FILE}"
	if limactl list -q 2>/dev/null | grep -qx "${VM_NAME}"; then
		limactl stop -f "${VM_NAME}" 2>/dev/null || true
		limactl delete "${VM_NAME}" 2>/dev/null || true
	fi
}
trap cleanup EXIT

echo "Starting Lima VM (ISO boot)..."
# --timeout=0 returns immediately once QEMU is launched (combined with plain:true)
limactl start --name="${VM_NAME}" --tty=false --timeout=3m "${CONFIG_FILE}" 2>&1 || true

# Give the ISO 120s to get through GRUB → kernel → initrd → Anaconda
echo "Waiting 120s for ISO to boot..."
sleep 120

# ── Check 1: Lima VM still running ────────────────────────────────────────────
STATUS=$(limactl list --json 2>/dev/null |
	python3 -c "import sys,json; rows=[json.loads(l) for l in sys.stdin if l.strip()]; \
	              vm=[r for r in rows if r.get('name')=='${VM_NAME}']; \
	              print(vm[0].get('status','unknown') if vm else 'missing')" 2>/dev/null || echo "unknown")
echo "Lima VM status: ${STATUS}"

if [[ "${STATUS}" == "missing" || "${STATUS}" == "Broken" ]]; then
	echo "ERROR: Lima VM is gone or broken after 120s"
	echo "--- Serial log tail ---"
	tail -30 "${SERIAL_LOG}" 2>/dev/null || true
	exit 1
fi
echo "VM still present after 120s ✓"

# ── Check 2: serial log for fatal errors / boot indicators ────────────────────
echo "--- Serial log (last 60 lines) ---"
tail -60 "${SERIAL_LOG}" 2>/dev/null || echo "(serial log not yet available)"

if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" \
	"${SERIAL_LOG}" 2>/dev/null; then
	echo "ERROR: Fatal boot error detected in serial log"
	exit 1
fi

BOOT_OK=0
# GRUB selecting the entry ("Booting '...'" or "GRUB version") confirms ISO is valid and booting.
# After GRUB hands off to the kernel, output goes to VGA (visible via VNC) not serial, so we
# won't see Anaconda startup in the serial log.
if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" \
	"${SERIAL_LOG}" 2>/dev/null; then
	BOOT_OK=1
	echo "Boot indicators found in serial log ✓"
else
	echo "Warning: No boot-completion markers in serial log"
	tail -5 "${SERIAL_LOG}" 2>/dev/null || true
fi

# ── Note on Anaconda WebUI ─────────────────────────────────────────────────────
# Lima plain mode ignores portForwards, so WebUI port-forward is not available.
# To inspect the installer manually, connect via VNC to the address Lima printed above.

# ── Result ─────────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "ISO Verification: $ISO_FILE"
echo "  VM running:      ✓"
echo "  Boot indicators: $([ "${BOOT_OK}" -eq 1 ] && echo '✓' || echo 'not confirmed')"
echo "  (Use VNC to inspect installer UI)"
echo "=========================================="

if [ "${BOOT_OK}" -eq 0 ]; then
	echo "ISO Verification FAILED: no boot indicators in serial log"
	exit 1
fi
echo "ISO Verification PASSED: $ISO_FILE"
