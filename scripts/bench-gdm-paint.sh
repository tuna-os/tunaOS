#!/usr/bin/env bash
# scripts/bench-gdm-paint.sh — measure GDM first-paint latency under a given
# QEMU config, for tuna-os/tunaos#581 (GDM slow/black under plain
# QEMU/virtio-vga on hosted-runner llvmpipe).
#
# Boots a pre-built qcow2 (e.g. `just qcow2 ghcr.io/tuna-os/yellowfin:gnome
# ghcr`) with -snapshot (so the base disk is never mutated — the same qcow2
# can be reused across every config in the matrix) and polls until either the
# framebuffer stops being blank (screendump stddev, same 0.02 floor iso-e2e.sh
# uses) or the serial console reaches graphical.target, recording whichever
# comes first plus the other for comparison. Prints one JSON object to stdout.
#
# Usage:
#   bench-gdm-paint.sh <qcow2> [--label NAME] [--machine pc|q35]
#                       [--vga virtio|std|cirrus] [--cpus N] [--memory MB]
#                       [--timeout SEC] [--output-dir DIR]
set -euo pipefail

QCOW2="${1:?usage: $0 <qcow2> [--label NAME] [--machine pc|q35] [--vga virtio|std|cirrus] [--cpus N] [--memory MB] [--timeout SEC] [--output-dir DIR]}"
shift

LABEL="bench"
MACHINE="pc"
VGA="virtio"
CPUS=4
MEMORY=4096
TIMEOUT=300
OUTPUT_DIR="./bench-out"
POLL_INTERVAL=3

while [[ $# -gt 0 ]]; do
	case "$1" in
	--label) LABEL="$2"; shift 2 ;;
	--machine) MACHINE="$2"; shift 2 ;;
	--vga) VGA="$2"; shift 2 ;;
	--cpus) CPUS="$2"; shift 2 ;;
	--memory) MEMORY="$2"; shift 2 ;;
	--timeout) TIMEOUT="$2"; shift 2 ;;
	--output-dir) OUTPUT_DIR="$2"; shift 2 ;;
	*) echo "unknown arg: $1" >&2; exit 2 ;;
	esac
done

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(realpath "$OUTPUT_DIR")"
QCOW2="$(realpath "$QCOW2")"

MONITOR_SOCK="${OUTPUT_DIR}/${LABEL}.monitor.sock"
SERIAL_LOG="${OUTPUT_DIR}/${LABEL}.serial.log"
QEMU_PIDFILE="${OUTPUT_DIR}/${LABEL}.qemu.pid"
OVMF_VARS="${OUTPUT_DIR}/${LABEL}.OVMF_VARS.fd"
rm -f "$MONITOR_SOCK" "$SERIAL_LOG" "$QEMU_PIDFILE" "$OVMF_VARS"

QEMU=""
for candidate in /usr/libexec/qemu-kvm /usr/bin/qemu-kvm /usr/bin/qemu-system-x86_64; do
	[[ -x "$candidate" ]] && { QEMU="$candidate"; break; }
done
[[ -z "$QEMU" ]] && { echo "ERROR: QEMU not found" >&2; exit 77; }

OVMF_CODE=""
for f in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd /usr/share/edk2-ovmf/x64/OVMF_CODE.fd; do
	[[ -f "$f" ]] && { OVMF_CODE="$f"; break; }
done
OVMF_VARS_SRC=""
for f in /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd /usr/share/edk2/ovmf/OVMF_VARS.fd /usr/share/edk2-ovmf/x64/OVMF_VARS.fd; do
	[[ -f "$f" ]] && { OVMF_VARS_SRC="$f"; break; }
done
[[ -z "$OVMF_CODE" ]] && { echo "ERROR: OVMF not found" >&2; exit 77; }
if [[ -n "$OVMF_VARS_SRC" ]]; then cp -f "$OVMF_VARS_SRC" "$OVMF_VARS"; else truncate -s 4M "$OVMF_VARS"; fi

ACCEL="tcg"
[[ -r /dev/kvm && -w /dev/kvm ]] && ACCEL="kvm"
CPU_ARG="qemu64"
[[ "$ACCEL" == "kvm" ]] && CPU_ARG="host"

case "$VGA" in
virtio) VGA_ARGS=(-vga virtio -display none) ;;
std) VGA_ARGS=(-vga std -display none) ;;
cirrus) VGA_ARGS=(-vga cirrus -display none) ;;
*) echo "unknown --vga: $VGA (want virtio|std|cirrus)" >&2; exit 2 ;;
esac

QEMU_PID=""
cleanup() {
	if [[ -n "$QEMU_PID" ]]; then
		kill -TERM "$QEMU_PID" 2>/dev/null || true
		sleep 1
		kill -KILL "$QEMU_PID" 2>/dev/null || true
	fi
}
trap cleanup EXIT

echo "==> [$LABEL] machine=$MACHINE vga=$VGA cpus=$CPUS accel=$ACCEL timeout=${TIMEOUT}s" >&2
BOOT_START=$(date +%s)
"$QEMU" \
	-name "gdm-bench-${LABEL}" \
	-machine "$MACHINE" \
	-cpu "$CPU_ARG" \
	-accel "$ACCEL" \
	-m "$MEMORY" \
	-smp "$CPUS" \
	-drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}" \
	-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
	-drive "if=none,id=disk,file=${QCOW2},format=qcow2,snapshot=on" \
	-device virtio-blk-pci,drive=disk \
	-monitor "unix:${MONITOR_SOCK},server,nowait" \
	-serial "file:${SERIAL_LOG}" \
	"${VGA_ARGS[@]}" \
	-pidfile "$QEMU_PIDFILE" \
	-daemonize

sleep 2
QEMU_PID="$(cat "$QEMU_PIDFILE" 2>/dev/null || true)"
if [[ -z "$QEMU_PID" ]] || ! kill -0 "$QEMU_PID" 2>/dev/null; then
	echo "ERROR: [$LABEL] QEMU failed to start" >&2
	printf '{"label":%s,"machine":%s,"vga":%s,"cpus":%s,"accel":%s,"error":"qemu_failed_to_start"}\n' \
		"\"$LABEL\"" "\"$MACHINE\"" "\"$VGA\"" "$CPUS" "\"$ACCEL\""
	exit 1
fi

paint_s=""
graphical_s=""
elapsed=0
while [[ "$elapsed" -lt "$TIMEOUT" ]]; do
	if [[ -z "$graphical_s" ]] && grep -qE "Reached target.*Graphical" "$SERIAL_LOG" 2>/dev/null; then
		graphical_s=$elapsed
		echo "==> [$LABEL] graphical.target reached at ${elapsed}s" >&2
	fi

	if [[ -z "$paint_s" ]]; then
		ppm="${OUTPUT_DIR}/${LABEL}-${elapsed}.ppm"
		echo "screendump ${ppm}" | socat - "UNIX-CONNECT:${MONITOR_SOCK}" >/dev/null 2>&1 || true
		if [[ -f "$ppm" ]]; then
			stddev=$(convert "$ppm" -colorspace Gray -format "%[fx:standard_deviation]" info: 2>/dev/null || echo 0)
			rm -f "$ppm"
			if awk -v s="$stddev" 'BEGIN{exit !(s > 0.02)}'; then
				paint_s=$elapsed
				echo "==> [$LABEL] screen painted (stddev=${stddev}) at ${elapsed}s" >&2
			fi
		fi
	fi

	[[ -n "$paint_s" && -n "$graphical_s" ]] && break

	sleep "$POLL_INTERVAL"
	elapsed=$(($(date +%s) - BOOT_START))
done

timed_out=false
[[ -z "$paint_s" && -z "$graphical_s" ]] && timed_out=true

printf '{"label":%s,"machine":%s,"vga":%s,"cpus":%s,"accel":%s,"paint_s":%s,"graphical_target_s":%s,"timed_out":%s}\n' \
	"\"$LABEL\"" "\"$MACHINE\"" "\"$VGA\"" "$CPUS" "\"$ACCEL\"" \
	"${paint_s:-null}" "${graphical_s:-null}" "$timed_out"
