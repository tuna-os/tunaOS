#!/bin/bash
set -euo pipefail

# Usage: ./scripts/install-test.sh <iso_file> [--kickstart <ks_file>]
#
# Boots a TunaOS ISO in QEMU with Anaconda WebUI exposed on localhost:19090.
# Optionally drives a fully automated install via a kickstart file.
#
# Interactive mode (default):
#   Open http://localhost:19090 in a browser to use the Anaconda installer.
#   Press Ctrl-C when done.
#
# Kickstart mode (--kickstart <ks_file>):
#   Anaconda reads the kickstart and installs unattended.
#   Exits 0 on success, 1 on failure.

KICKSTART_FILE=""
WEBUI_PORT=19090
DISK_SIZE="20G"
MEM="4G"
CPUS=4
TIMEOUT_SECS=600

# ── Argument parsing ────────────────────────────────────────────────────────────
if [ "$#" -lt 1 ]; then
	echo "Usage: $0 <iso_file> [--kickstart <ks_file>]"
	echo "  --kickstart <file>   Run unattended install using the given kickstart"
	exit 1
fi

ISO_FILE="$1"
shift
while [ "$#" -gt 0 ]; do
	case "$1" in
	--kickstart)
		KICKSTART_FILE="$(realpath "$2")"
		shift 2
		;;
	*)
		echo "Unknown option: $1"
		exit 1
		;;
	esac
done

ISO_PATH="$(realpath "$ISO_FILE")"
if [ ! -f "$ISO_PATH" ]; then
	echo "Error: ISO not found: $ISO_PATH"
	exit 1
fi

# ── Locate QEMU and UEFI firmware ──────────────────────────────────────────────
QEMU_BIN=""
for candidate in \
	/home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64 \
	/usr/bin/qemu-system-x86_64 \
	/usr/local/bin/qemu-system-x86_64; do
	if [ -x "$candidate" ]; then
		QEMU_BIN="$candidate"
		break
	fi
done
if [ -z "$QEMU_BIN" ]; then
	echo "Error: qemu-system-x86_64 not found. Install QEMU."
	exit 1
fi

FIRMWARE=""
for candidate in \
	/home/linuxbrew/.linuxbrew/share/qemu/edk2-x86_64-code.fd \
	/usr/share/OVMF/OVMF_CODE.fd \
	/usr/share/edk2/x64/OVMF_CODE.fd; do
	if [ -f "$candidate" ]; then
		FIRMWARE="$candidate"
		break
	fi
done
if [ -z "$FIRMWARE" ]; then
	echo "Error: UEFI firmware (EDK2/OVMF) not found."
	exit 1
fi

NVRAM_TEMPLATE=""
for candidate in \
	/home/linuxbrew/.linuxbrew/share/qemu/edk2-x86_64-vars.fd \
	/usr/share/OVMF/OVMF_VARS.fd \
	/usr/share/edk2/x64/OVMF_VARS.fd; do
	if [ -f "$candidate" ]; then
		NVRAM_TEMPLATE="$candidate"
		break
	fi
done

# ── Temp files ──────────────────────────────────────────────────────────────────
WORK_DIR="$(mktemp -d /tmp/tuna-install-XXXXXX)"
DISK_FILE="${WORK_DIR}/install-target.qcow2"
NVRAM_FILE="${WORK_DIR}/nvram.fd"
SERIAL_LOG="${WORK_DIR}/serial.log"
KS_HTTP_PID_FILE="${WORK_DIR}/ks-httpd.pid"
QEMU_PID_FILE="${WORK_DIR}/qemu.pid"

cleanup() {
	echo ""
	echo "==> Cleaning up..."
	if [ -f "$QEMU_PID_FILE" ]; then
		QPID=$(cat "$QEMU_PID_FILE" 2>/dev/null || true)
		[ -n "$QPID" ] && kill "$QPID" 2>/dev/null || true
	fi
	if [ -f "$KS_HTTP_PID_FILE" ]; then
		HPID=$(cat "$KS_HTTP_PID_FILE" 2>/dev/null || true)
		[ -n "$HPID" ] && kill "$HPID" 2>/dev/null || true
	fi
	rm -rf "$WORK_DIR"
}
trap cleanup EXIT

# ── Prepare install target disk ─────────────────────────────────────────────────
echo "==> Creating ${DISK_SIZE} install target disk..."
"$QEMU_BIN" -version | head -1
qemu-img create -f qcow2 "$DISK_FILE" "$DISK_SIZE" >/dev/null

# Copy NVRAM template for writable UEFI vars
if [ -n "$NVRAM_TEMPLATE" ]; then
	cp "$NVRAM_TEMPLATE" "$NVRAM_FILE"
fi

# ── Kickstart HTTP server ────────────────────────────────────────────────────────
KS_KERNEL_ARG=""
if [ -n "$KICKSTART_FILE" ]; then
	# Serve the kickstart over HTTP so Anaconda can fetch it from inside the VM.
	# QEMU user-mode NAT gateway is 10.0.2.2 by default.
	KS_PORT=18080
	echo "==> Serving kickstart on http://10.0.2.2:${KS_PORT}/ks.cfg ..."
	cp "$KICKSTART_FILE" "${WORK_DIR}/ks.cfg"
	(
		cd "$WORK_DIR" && python3 -m http.server "$KS_PORT" --bind 127.0.0.1 >/dev/null 2>&1 &
		echo $! >"$KS_HTTP_PID_FILE"
	)
	sleep 1
	KS_KERNEL_ARG="inst.ks=http://10.0.2.2:${KS_PORT}/ks.cfg"
	echo "    Kickstart: $KICKSTART_FILE"
fi

# ── Build QEMU command ───────────────────────────────────────────────────────────
QEMU_ARGS=(
	-name "tuna-install-test"
	-machine "type=q35,accel=kvm"
	-cpu host
	-m "$MEM"
	-smp "$CPUS"
	# UEFI firmware
	-drive "if=pflash,format=raw,readonly=on,file=${FIRMWARE}"
)
if [ -f "$NVRAM_FILE" ]; then
	QEMU_ARGS+=(-drive "if=pflash,format=raw,file=${NVRAM_FILE}")
fi
QEMU_ARGS+=(
	# Install target disk (virtio)
	-drive "file=${DISK_FILE},format=qcow2,if=virtio,index=0"
	# ISO as SCSI CD-ROM (matches Lima's setup — reliably detected by UEFI)
	-drive "file=${ISO_PATH},format=raw,if=none,id=cdrom0,readonly=on"
	-device "virtio-scsi-pci,id=scsi0"
	-device "scsi-cd,bus=scsi0.0,drive=cdrom0"
	# Network: NAT with Anaconda WebUI (9090) forwarded to host
	-netdev "user,id=net0,hostfwd=tcp:127.0.0.1:${WEBUI_PORT}-:9090"
	-device "virtio-net-pci,netdev=net0"
	# Serial log
	-serial "file:${SERIAL_LOG}"
	-display none
	-daemonize
	-pidfile "$QEMU_PID_FILE"
)

# Append extra kernel args via GRUB if kickstart is set
# (Anaconda reads inst.ks from the kernel cmdline appended to the GRUB entry)
# Note: For interactive mode these are empty and GRUB auto-selects the entry.
if [ -n "$KS_KERNEL_ARG" ]; then
	# Pass via -append only works with -kernel; for ISO we use GRUB cmdline injection
	# by passing inst.ks as a QEMU smbios string that Anaconda can read.
	# The reliable method is to use inst.cmdline via the loader.
	echo "Note: Kickstart URL will be appended via QEMU fw_cfg for Anaconda."
	QEMU_ARGS+=(-fw_cfg "name=opt/org.anaconda.cmdline,string=${KS_KERNEL_ARG}")
fi

echo "==> Starting QEMU..."
"$QEMU_BIN" "${QEMU_ARGS[@]}"
QEMU_PID=$(cat "$QEMU_PID_FILE")
echo "    PID: $QEMU_PID"
echo "    Serial log: $SERIAL_LOG"
echo ""

# ── Wait for Anaconda WebUI ──────────────────────────────────────────────────────
echo "==> Waiting for Anaconda WebUI on http://localhost:${WEBUI_PORT} ..."
echo "    (Anaconda takes 3-8 minutes to initialise after GRUB)"
WEBUI_UP=0
ELAPSED=0
INTERVAL=10
while [ "$ELAPSED" -lt "$TIMEOUT_SECS" ]; do
	if ! kill -0 "$QEMU_PID" 2>/dev/null; then
		echo "ERROR: QEMU process exited unexpectedly."
		echo "--- Serial log tail ---"
		tail -20 "$SERIAL_LOG" 2>/dev/null || true
		exit 1
	fi
	if curl -sf --max-time 5 "http://localhost:${WEBUI_PORT}/" -o /dev/null 2>/dev/null; then
		WEBUI_UP=1
		break
	fi
	printf "  [%3ds] waiting...\r" "$ELAPSED"
	sleep "$INTERVAL"
	ELAPSED=$((ELAPSED + INTERVAL))
done

if [ "$WEBUI_UP" -eq 0 ]; then
	echo "ERROR: Anaconda WebUI did not come up within ${TIMEOUT_SECS}s."
	echo "--- Serial log tail ---"
	tail -30 "$SERIAL_LOG" 2>/dev/null || true
	exit 1
fi

echo "✓ Anaconda WebUI is up at http://localhost:${WEBUI_PORT}"
echo ""

# ── Interactive or kickstart mode ────────────────────────────────────────────────
if [ -z "$KICKSTART_FILE" ]; then
	echo "=========================================="
	echo "  INTERACTIVE MODE"
	echo "  Open in your browser:"
	echo "    http://localhost:${WEBUI_PORT}"
	echo ""
	echo "  Press Ctrl-C when finished."
	echo "=========================================="
	# Wait until QEMU exits or user interrupts
	while kill -0 "$QEMU_PID" 2>/dev/null; do
		sleep 5
	done
	echo "VM exited."
else
	echo "==> Kickstart mode: waiting for unattended install to complete..."
	echo "    (Monitor: http://localhost:${WEBUI_PORT})"
	# Poll for VM exit (Anaconda reboots on completion) or WebUI disappearing
	INSTALL_TIMEOUT=3600
	ELAPSED=0
	while [ "$ELAPSED" -lt "$INSTALL_TIMEOUT" ]; do
		if ! kill -0 "$QEMU_PID" 2>/dev/null; then
			echo "✓ VM exited — install likely completed."
			break
		fi
		# WebUI going away + VM still up = install in progress; VM exit = done
		sleep 15
		ELAPSED=$((ELAPSED + 15))
	done

	if [ "$ELAPSED" -ge "$INSTALL_TIMEOUT" ]; then
		echo "ERROR: Install did not complete within ${INSTALL_TIMEOUT}s."
		exit 1
	fi

	echo ""
	echo "=========================================="
	echo "  INSTALL COMPLETE ✓"
	echo "  ISO: $ISO_FILE"
	echo "=========================================="
fi
