#!/usr/bin/env bash
# scripts/run-walkthrough.sh — Automate GUI installer walkthrough & take screenshots

set -euo pipefail

ISO_PATH="${1:?usage: $0 <iso_path> [output_dir]}"
OUTPUT_DIR="${2:-./walkthrough-out}"

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(realpath "$OUTPUT_DIR")"
ISO_PATH="$(realpath "$ISO_PATH")"

MONITOR_SOCK="${OUTPUT_DIR}/monitor.sock"
SERIAL_LOG="${OUTPUT_DIR}/serial.log"
INSTALL_DISK="${OUTPUT_DIR}/install-disk.qcow2"
QEMU_PIDFILE="${OUTPUT_DIR}/qemu.pid"
OVMF_VARS="${OUTPUT_DIR}/OVMF_VARS.fd"

# Locate QEMU and OVMF
QEMU=""
for candidate in /usr/libexec/qemu-kvm /usr/bin/qemu-kvm /usr/bin/qemu-system-x86_64; do
	if [[ -x "$candidate" ]]; then
		QEMU="$candidate"
		break
	fi
done
if [[ -z "$QEMU" ]]; then
	echo "ERROR: QEMU not found" >&2
	exit 1
fi

OVMF_CODE=""
for f in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd /usr/share/edk2-ovmf/x64/OVMF_CODE.fd; do
	if [[ -f "$f" ]]; then
		OVMF_CODE="$f"
		break
	fi
done
OVMF_VARS_SRC=""
for f in /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd /usr/share/edk2/ovmf/OVMF_VARS.fd /usr/share/edk2-ovmf/x64/OVMF_VARS.fd; do
	if [[ -f "$f" ]]; then
		OVMF_VARS_SRC="$f"
		break
	fi
done
if [[ -z "$OVMF_CODE" ]]; then
	echo "ERROR: OVMF not found" >&2
	exit 1
fi

# Accel
ACCEL="tcg"
if [[ -r /dev/kvm ]] && [[ -w /dev/kvm ]]; then ACCEL="kvm"; fi
CPU_ARG="qemu64"
if [[ "$ACCEL" == "kvm" ]]; then CPU_ARG="host"; fi

# Clean files
rm -f "$MONITOR_SOCK" "$SERIAL_LOG" "$QEMU_PIDFILE"
if [[ -n "$OVMF_VARS_SRC" ]]; then cp -f "$OVMF_VARS_SRC" "$OVMF_VARS"; else truncate -s 4M "$OVMF_VARS"; fi
rm -f "$INSTALL_DISK" && qemu-img create -f qcow2 "$INSTALL_DISK" 15G

# Clean exiting
cleanup_vm() {
	if [[ -f "$QEMU_PIDFILE" ]]; then
		local pid
		pid=$(cat "$QEMU_PIDFILE" 2>/dev/null || true)
		if [[ -n "$pid" ]]; then
			kill -TERM "$pid" 2>/dev/null || true
			sleep 2
			kill -KILL "$pid" 2>/dev/null || true
		fi
	fi
}
trap cleanup_vm EXIT

# Display path. `-vga virtio -display none` gives no GL, and cosmic, niri and
# xfwl4 are Smithay compositors that hard-require EGL_EXT_device_drm — they do
# not fall back to software, they simply never start. So on a host with a DRM
# render node, switch to virgl and attach VNC:
#
#   * virtio-vga-gl + egl-headless is what makes those sessions render at all;
#   * -vnc is what makes them photographable, because screendump answers
#     "Error: no surface" once a guest scans out through GL.
#
# Auto-detected rather than flagged, so the same command does the right thing
# on a GPU host and on a hosted runner. TBOX_WALKTHROUGH_GPU=0 forces it off.
RENDERNODE="${TBOX_WALKTHROUGH_RENDERNODE:-/dev/dri/renderD128}"
VNC_SOCK="${OUTPUT_DIR}/vnc.sock"
rm -f "$VNC_SOCK"
DISPLAY_ARGS=(-vga virtio -display none)
if [[ "${TBOX_WALKTHROUGH_GPU:-1}" != "0" && -e "$RENDERNODE" ]] &&
	"$QEMU" -device help 2>/dev/null | grep -q virtio-vga-gl &&
	"$QEMU" -display help 2>/dev/null | grep -q egl-headless; then
	echo "==> GPU path: virgl via ${RENDERNODE}, VNC at ${VNC_SOCK}"
	DISPLAY_ARGS=(
		-device virtio-vga-gl
		-display "egl-headless,rendernode=${RENDERNODE}"
		-vnc "unix:${VNC_SOCK}"
	)
else
	echo "==> No GL path (no ${RENDERNODE} or QEMU lacks virgl)."
	echo "    cosmic/niri/xfwl4 will not start; kde needs it too. Expect blank frames."
fi

echo "==> Booting VM under $ACCEL..."
"$QEMU" \
	-name "tunaos-walkthrough" \
	-machine pc \
	-cpu "$CPU_ARG" \
	-accel "$ACCEL" \
	-m 4096 \
	-smp 4 \
	-drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}" \
	-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
	-drive "if=none,id=iso,file=${ISO_PATH},media=cdrom,readonly=on,format=raw" \
	-device virtio-scsi-pci,id=scsi \
	-device scsi-cd,drive=iso \
	-drive "if=none,id=disk,file=${INSTALL_DISK},format=qcow2" \
	-device virtio-blk-pci,drive=disk \
	-monitor "unix:${MONITOR_SOCK},server,nowait" \
	-serial "file:${SERIAL_LOG}" \
	"${DISPLAY_ARGS[@]}" \
	-pidfile "$QEMU_PIDFILE" \
	-daemonize

sleep 5
if ! kill -0 "$(cat "$QEMU_PIDFILE")" 2>/dev/null; then
	echo "ERROR: QEMU failed to start"
	exit 1
fi

send_key() {
	local key="$1"
	echo "==> Pressing $key..."
	echo "sendkey $key" | socat - "UNIX-CONNECT:${MONITOR_SOCK}" >/dev/null 2>&1
	sleep 2
}

take_screenshot() {
	local name="$1"
	local ppm="${OUTPUT_DIR}/${name}.ppm"
	local png="${OUTPUT_DIR}/${name}.png"

	# VNC first — on the GL path screendump has no surface to dump, so this is
	# the only capture that works for exactly the desktops we most need to see.
	if [[ -S "$VNC_SOCK" ]] && command -v vncdo &>/dev/null; then
		local port="${TBOX_WALKTHROUGH_VNC_PORT:-5998}"
		socat "TCP-LISTEN:${port},reuseaddr,fork" "UNIX-CONNECT:${VNC_SOCK}" &
		local bridge=$!
		sleep 1
		vncdo -s "127.0.0.1::${port}" capture "$png" >/dev/null 2>&1 || true
		kill "$bridge" 2>/dev/null || true
		if [[ -s "$png" ]]; then
			echo "✓ Captured: ${png} (vnc)"
			return 0
		fi
	fi

	echo "screendump ${ppm}" | socat - "UNIX-CONNECT:${MONITOR_SOCK}" >/dev/null 2>&1
	sleep 1
	if [[ -f "$ppm" ]]; then
		pnmtopng "$ppm" >"$png" 2>/dev/null || python3 -c "from PIL import Image; Image.open('$ppm').save('$png')" 2>/dev/null
		rm -f "$ppm"
		echo "✓ Captured: ${png} (screendump)"
	else
		echo "✗ Failed screenshot: ${name} (no GL surface, and no usable VNC at ${VNC_SOCK})"
	fi
}

echo "Waiting for installer boot (45 seconds)..."
sleep 45
take_screenshot "01_welcome"

# Go from Page 0 (Welcome) -> Page 1 (Disk Select)
send_key "ret"
take_screenshot "02_disk_select"

# Select default disk and Continue to Page 2 (Confirm)
send_key "tab"
send_key "tab"
send_key "ret"
take_screenshot "03_confirm"

# Confirm and start install Page 3 (Installing)
send_key "tab"
send_key "ret"
take_screenshot "04_installing"

echo "Waiting for installation progress (60 seconds)..."
sleep 60
take_screenshot "05_installing_progress"

echo "Waiting for installation to finish (60 seconds)..."
sleep 60
take_screenshot "06_done"

# Quit/Restart
send_key "ret"

echo "==> Walkthrough automation complete!"
ls -lh "$OUTPUT_DIR"
