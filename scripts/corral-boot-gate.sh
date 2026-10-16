#!/usr/bin/env bash
# scripts/corral-boot-gate.sh — the disk boot gate, run by Corral.
#
# Installs a bootc image to a disk with `corral vmtest`, boots it under QEMU/KVM
# on UEFI, and gates on the contract markers the image prints on its serial
# console. It replaces `just qcow2` + `scripts/iso-e2e.sh --disk` for the
# boot gate, and keeps that pair's verdict:
#
#   pass  TUNAOS_DESKTOP_CONTRACT_OK (or TUNAOS_BASE_CONTRACT_OK with
#         DISK_CONTRACT=base) on the console, and no
#         TUNAOS_BASE_CONTRACT_FAIL within BASE_CONTRACT_GRACE seconds of the
#         desktop marker (tunaOS#2664)
#   fail  a contract FAIL marker, an emergency shell, or a kernel panic on the
#         console. Corral ends the wait the moment one appears.
#   fail  no marker within the timeout
#
# The disk matches `just qcow2`: the same root filesystem rule (ext4 for a
# sealed image, else xfs, TUNAOS_QCOW2_FILESYSTEM overrides) and the same
# kernel arguments. tunaos.countme=0 is in the boot entry from the first boot,
# so a gate guest never sends an adoption report (docs/ci-troubleshooting.md).
#
# Usage:
#   sudo scripts/corral-boot-gate.sh <image-ref> <output-dir> [timeout-seconds]
#
# Writes into <output-dir>:
#   serial.log             the guest console (evidence-bundle.sh reads it)
#   *.png, timelapse.webm  the screen when the run ended, and the boot
#   corral/                Corral's own artifacts: result.json, frames/,
#                          diagnostics/
#
# Environment:
#   CORRAL                 corral binary (default: corral on PATH)
#   DISK_CONTRACT          desktop (default) or base
#   BASE_CONTRACT_GRACE    seconds to wait for the base marker after the
#                          desktop marker (default: 120)
#   TUNAOS_QCOW2_FILESYSTEM  root filesystem override, as for `just qcow2`
#   GATE_NAME              VM name (default: tunaos-gate-<pid>-<epoch>, unique per run)
#   GATE_CPUS / GATE_MEMORY / GATE_DISK  (default: 4 / 4G / 40G)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/backend.sh
source "${SCRIPT_DIR}/lib/backend.sh"

IMAGE="${1:?usage: $0 <image-ref> <output-dir> [timeout-seconds]}"
OUT="${2:?usage: $0 <image-ref> <output-dir> [timeout-seconds]}"
TIMEOUT="${3:-900}"
CORRAL="${CORRAL:-corral}"
NAME="${GATE_NAME:-tunaos-gate-$$-$(date +%s)}"
GRACE="${BASE_CONTRACT_GRACE:-120}"

case "${DISK_CONTRACT:-desktop}" in
desktop) READY='TUNAOS_DESKTOP_CONTRACT_OK' ;;
base) READY='TUNAOS_BASE_CONTRACT_OK' ;;
*)
	echo "ERROR: DISK_CONTRACT must be 'desktop' or 'base', got '${DISK_CONTRACT}'" >&2
	exit 1
	;;
esac
# The signatures scripts/iso-e2e.sh treats as a definitive boot failure
# (boot_failed_on_serial), plus both contracts' own FAIL markers.
FAIL='TUNAOS_(DESKTOP|BASE)_CONTRACT_FAIL|Entering emergency mode|Dracut Emergency Shell|Warning: Could not boot|Kernel panic|You are in emergency mode'

if [[ "$(id -u)" -ne 0 ]]; then
	echo "ERROR: run as root: bootc install partitions a disk and installs a bootloader" >&2
	exit 1
fi
command -v "$CORRAL" >/dev/null || {
	echo "ERROR: corral not found (set CORRAL or put it on PATH)" >&2
	exit 1
}
"$CORRAL" vmtest --help 2>&1 | grep -q -- '--fail-marker' || {
	echo "ERROR: $CORRAL has no vmtest --fail-marker; install a corral that has it" >&2
	exit 1
}

# The filesystem `just qcow2` would install on. Probe failures are fatal there
# and here: guessing ostree/xfs for a sealed image boots into dracut.
PROBE=$(probe_image_backend "$IMAGE" podman)
echo "==> image probe: $(tr '\n' ' ' <<<"$PROBE")"
FS=xfs
grep -q '^SEALED=1$' <<<"$PROBE" && FS=ext4
if [[ -n "${TUNAOS_QCOW2_FILESYSTEM:-}" ]]; then
	echo "==> TUNAOS_QCOW2_FILESYSTEM=${TUNAOS_QCOW2_FILESYSTEM} overriding probed filesystem"
	FS="$TUNAOS_QCOW2_FILESYSTEM"
fi

mkdir -p "$OUT"
# The VM is kept after a pass so the base contract can still report below;
# it goes when this script does, whatever the outcome.
trap '"$CORRAL" delete "$NAME" -f >/dev/null 2>&1 || true' EXIT

# Kernel arguments as in just/qcow2-build.just. Corral puts
# console=ttyS0,115200n8 first; naming ttyS0 again after tty0 keeps it the
# primary console, where systemd and the base contract write.
rc=0
"$CORRAL" vmtest "$NAME" \
	--bootc "$IMAGE" \
	--cpu "${GATE_CPUS:-4}" --mem "${GATE_MEMORY:-4G}" --disk "${GATE_DISK:-40G}" \
	--filesystem "$FS" \
	--karg console=tty0 --karg console=ttyS0,115200n8 \
	--karg systemd.journald.forward_to_console=1 \
	--karg systemd.unit=graphical.target \
	--karg tunaos.countme=0 \
	--ready-marker "$READY" \
	--fail-marker "$FAIL" \
	--timeout "${TIMEOUT}s" \
	--artifacts "${OUT}/corral" \
	--video || rc=$?

# The live console, which keeps growing after the copy in the artifacts. Corral
# keeps its VMs under the invoking user's home, which is root's here.
SERIAL="${HOME}/.local/share/corral/vms/${NAME}/serial.log"
[[ -f "$SERIAL" ]] || SERIAL="${OUT}/corral/serial.log"

if [[ "$rc" -eq 0 && "${DISK_CONTRACT:-desktop}" == desktop ]]; then
	# A desktop with no system bus is not a working desktop (tunaOS#2664). The
	# base contract can report after the desktop one, so give it the same
	# grace scripts/iso-e2e.sh does.
	deadline=$(($(date +%s) + GRACE))
	until grep -qE 'TUNAOS_BASE_CONTRACT_(OK|FAIL)' "$SERIAL" 2>/dev/null; do
		if (($(date +%s) >= deadline)); then
			echo "WARN: no TUNAOS_BASE_CONTRACT_* marker within ${GRACE}s of the desktop marker; system bus unverified" >&2
			break
		fi
		sleep 1
	done
	if grep -q 'TUNAOS_BASE_CONTRACT_FAIL' "$SERIAL" 2>/dev/null; then
		echo "ERROR: the desktop contract passed, but the base contract FAILED on the same boot (tunaOS#2664):" >&2
		grep 'TUNAOS_BASE_CONTRACT_FAIL' "$SERIAL" | tr -d '\r' >&2
		rc=1
	fi
fi

# Corral's ready.png is the screen at the marker, and the greeter can paint
# after it. Like iso-e2e.sh's wait_for_paint, poll for a painted frame as
# evidence only: a slow or absent paint cannot change the verdict.
if [[ "$rc" -eq 0 ]]; then
	for _ in $(seq 1 12); do
		"$CORRAL" screenshot "$NAME" -o "${OUT}/10-ready.png" --require-paint >/dev/null 2>&1 && break
		sleep 5
	done
fi

cp -f "$SERIAL" "${OUT}/serial.log" 2>/dev/null || true
# The verdict is read off the console; a pass with no console to show for it
# is not evidence of anything.
if [[ "$rc" -eq 0 && ! -s "${OUT}/serial.log" ]]; then
	echo "ERROR: corral reported a pass but left no serial log at ${SERIAL}" >&2
	rc=1
fi
for f in ready.png failure.png timelapse.webm; do
	[[ -f "${OUT}/corral/${f}" ]] && cp -f "${OUT}/corral/${f}" "${OUT}/${f}"
done

# Installed-system TAP checks are advisory here, as in iso-e2e.sh.
if grep -q 'TUNAOS_INSTALL_CHECKS_RESULT' "${OUT}/serial.log" 2>/dev/null; then
	echo "==> Installed-system TAP checks (from serial console):"
	sed -n '/TUNAOS_INSTALL_CHECKS_BEGIN/,/TUNAOS_INSTALL_CHECKS_RESULT/p' "${OUT}/serial.log" | tr -d '\r'
fi

if [[ "$rc" -ne 0 && -s "${OUT}/serial.log" ]]; then
	echo "==> serial log: last 120 lines:" >&2
	tail -n 120 "${OUT}/serial.log" | sed 's/^/serial| /' >&2
fi
exit "$rc"
