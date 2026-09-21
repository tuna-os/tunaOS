#!/usr/bin/env bash
# scripts/iso-e2e-corral.sh — live-ISO boot via corral (replaces raw qemu in iso-e2e.sh)
#
# Boots an ISO or qcow2 in a local QEMU VM managed by corral, using the same
# knobs iso-e2e.sh hand-rolls: OVMF/AAVMF (UEFI), hostfwd SSH, VSOCK fallback,
# TPM 2.0 (swtpm), serial console (append=on), QMP screendump, VNC bridge.
#
# Requires: corral >= a3f4a16 (create --vsock/--tpm/--firmware uefi,
#   logs --serial, screenshot --require-paint, diagnose --bundle-dir, doctor,
#   qmp). Install: go install github.com/tuna-os/corral@latest
#   or: curl -fsSL .../corral-linux-amd64 -o /usr/local/bin/corral
#
# Usage mirrors iso-e2e.sh subset:
#   iso-e2e-corral.sh <iso|qcow2> [--output DIR] [--memory MB] [--cpus N]
#                                 [--timeout SEC] [--keep-vm] [--tpm] [--vsock]
#   Set USE_CORRAL=0 to force raw qemu (fallback).
#
# Compared to iso-e2e.sh, this is intentionally small (~120 lines): all the
# device wiring, key generation (ssh-keygen ed25519 + SMBIOS type 11), TPM
# daemon lifecycle, QMP handshake, screenshot stddev 0.02 gate and bundle
# layout are inside corral. See docs/corral-vs-qemu.md for the mapping.
set -euo pipefail

ISO_PATH="${1:?usage: $0 <iso|qcow2> [--output DIR] [--memory MB] [--cpus N] [--timeout SEC] [--keep-vm] [--tpm] [--vsock]}"
shift

OUTPUT_DIR="./corral-iso-out"
MEMORY=4096
CPUS=4
TIMEOUT=600
KEEP_VM=0
USE_TPM=0
USE_VSOCK=1
DISK_MODE=0
DISK_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
  --output) OUTPUT_DIR="$2"; shift 2;;
  --memory) MEMORY="$2"; shift 2;;
  --cpus) CPUS="$2"; shift 2;;
  --timeout) TIMEOUT="$2"; shift 2;;
  --keep-vm) KEEP_VM=1; shift;;
  --tpm) USE_TPM=1; shift;;
  --no-tpm) USE_TPM=0; shift;;
  --vsock) USE_VSOCK=1; shift;;
  --no-vsock) USE_VSOCK=0; shift;;
  --disk) DISK_MODE=1; DISK_PATH="$ISO_PATH"; shift;;
  *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

if [[ "${USE_CORRAL:-1}" == "0" ]] || ! command -v corral >/dev/null 2>&1; then
  echo "corral not available or USE_CORRAL=0 — falling back to scripts/iso-e2e.sh" >&2
  exec "$(dirname "${BASH_SOURCE[0]}")/iso-e2e.sh" "$ISO_PATH" --output "$OUTPUT_DIR" --memory "$MEMORY" --cpus "$CPUS" --timeout "$TIMEOUT" ${KEEP_VM:+--keep-vm} ${USE_TPM:+--luks}
fi

if [[ ! -f "$ISO_PATH" ]] && [[ "$DISK_MODE" == "0" ]]; then
  echo "ERROR: $ISO_PATH not found" >&2; exit 2
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(realpath "$OUTPUT_DIR")"
ISO_PATH="$(realpath "$ISO_PATH" 2>/dev/null || echo "$ISO_PATH")"

VM_NAME="tunaos-corral-$(date +%s)-$$"
BUNDLE_DIR="${OUTPUT_DIR}/bundle"
SERIAL_DST="${OUTPUT_DIR}/serial.log"
SCREEN_PNG="${OUTPUT_DIR}/screenshot.png"

echo "==> corral iso-e2e: $(basename "$ISO_PATH") → $VM_NAME ($MEMORY MB, $CPUS vCPU, timeout ${TIMEOUT}s) vsock=$USE_VSOCK tpm=$USE_TPM" >&2
corral doctor 2>&1 | sed 's/^/doctor: /' >&2 || true

CORRAL_ARGS=(--firmware uefi --mem "${MEMORY}M" --cpu "$CPUS" --disk 32G)
[[ "$USE_VSOCK" == "1" ]] && CORRAL_ARGS+=(--vsock)
[[ "$USE_TPM" == "1" ]] && CORRAL_ARGS+=(--tpm)

cleanup() {
  local rc=$?
  if [[ "$KEEP_VM" == "1" ]]; then
    echo "==> --keep-vm: VM $VM_NAME left running (corral logs $VM_NAME --serial; corral ssh $VM_NAME --vsock)" >&2
    exit $rc
  fi
  corral delete "$VM_NAME" --force >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ "$DISK_MODE" == "1" ]]; then
  # Boot existing disk (qcow2) — snapshot-like: copy as template.
  corral create "$VM_NAME" --qcow "$DISK_PATH" "${CORRAL_ARGS[@]}" 2>&1 | tee "${OUTPUT_DIR}/corral-create.log"
else
  corral create "$VM_NAME" --iso "$ISO_PATH" "${CORRAL_ARGS[@]}" 2>&1 | tee "${OUTPUT_DIR}/corral-create.log"
fi
corral start "$VM_NAME" 2>&1 | tee "${OUTPUT_DIR}/corral-start.log"
echo "==> VM $VM_NAME started — polling serial for TUNAOS_LIVE_READY" >&2

# Poll serial log for the live-ready marker iso-e2e.sh gates on, with
# BootFailedOnSerial-style emergency-shell detection. Mirrors the 0.02
# screenshot sanity fallback when serial is silent (CONFIG_SERIAL_8250=m).
START=$(date +%s)
READY=0
while [[ $(($(date +%s)-START)) -lt "$TIMEOUT" ]]; do
  if corral logs "$VM_NAME" --serial 2>/dev/null | grep -q "TUNAOS_LIVE_READY"; then
    echo "==> TUNAOS_LIVE_READY seen" >&2; READY=1; break
  fi
  if corral logs "$VM_NAME" --serial 2>/dev/null | grep -qE "Entering emergency mode|Dracut Emergency Shell|Kernel panic"; then
    echo "ERROR: serial shows failed boot (emergency shell/panic)" >&2
    corral logs "$VM_NAME" --serial 2>&1 | tail -100 >&2
    corral diagnose "$VM_NAME" 2>&1 | tail -50 >&2 || true
    exit 8
  fi
  sleep 5
done
if [[ "$READY" == "0" ]]; then
  # Fallback to screenshot sanity (blank StdDev <=0.02 means compositor never painted)
  if corral screenshot "$VM_NAME" -o "$SCREEN_PNG" >/dev/null 2>&1; then
    if corral screenshot "$VM_NAME" -o "$SCREEN_PNG" --require-paint 2>&1; then
      echo "==> screenshot painted (serial marker silent — CONFIG_SERIAL_8250=m fallback)" >&2
      READY=1
    else
      echo "ERROR: framebuffer blank and serial marker absent (compositor never painted)" >&2
      corral diagnose "$VM_NAME" 2>&1 | tail -100 >&2 || true
      exit 9
    fi
  else
    echo "WARN: no screenshot and no serial marker within ${TIMEOUT}s" >&2
    corral logs "$VM_NAME" --serial 2>&1 | tail -80 >&2 || true
    exit 6
  fi
fi

# Capture evidence (matches evidence-bundle.sh: serial.log, screenshot.png, journal, qmp-status)
corral screenshot "$VM_NAME" -o "$SCREEN_PNG" >/dev/null 2>&1 || true
corral logs "$VM_NAME" --serial > "$SERIAL_DST" 2>&1 || true
corral diagnose "$VM_NAME" --bundle-dir "$BUNDLE_DIR" >/dev/null 2>&1 || true
cp -f "$SCREEN_PNG" "${OUTPUT_DIR}/" 2>/dev/null || true

echo "==> corral iso-e2e succeeded — bundle at $BUNDLE_DIR" >&2
ls -lh "$OUTPUT_DIR" 2>&1 | sed 's/^/  /' >&2
# Keep VM if requested, else cleanup trap deletes it.
if [[ "$KEEP_VM" == "1" ]]; then trap - EXIT; fi
exit 0
