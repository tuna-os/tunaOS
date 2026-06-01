#!/usr/bin/env bash
# scripts/iso-e2e.sh — TunaOS live-ISO end-to-end smoke test.
#
# Boots a pre-built ISO in QEMU under OVMF (UEFI), waits for the TunaOS live
# readiness marker on the serial console, optionally runs an Anaconda
# kickstart install + reboots into the installed disk, and captures
# screenshots + serial logs for CI artifact upload.
#
# Modelled on projectbluefin/dakota-iso's luks-*-qemu recipes (see
# docs/IMPROVEMENT_PLAN.md §2 for design notes).
#
# Usage:
#   scripts/iso-e2e.sh <iso_path>
#       Boot-and-ready smoke only. Exits 0 if the live env reaches the
#       readiness marker within --timeout seconds.
#
#   scripts/iso-e2e.sh <iso_path> --kickstart <ks.cfg>
#       Boot, run an unattended Anaconda kickstart install onto a fresh
#       disk image, then boot the installed disk and confirm it reaches
#       multi-user.target.
#
#   scripts/iso-e2e.sh <iso_path> --ssh-only
#       Boot, then verify SSH connectivity to the live env. ISO must have
#       been built with ENABLE_SSHD=1 (e.g. `just live-iso dev=1`).
#
# Options:
#   --timeout SEC         Per-phase timeout (default: 300)
#   --output DIR          Where serial logs / screenshots are written
#                         (default: ./iso-e2e-out)
#   --memory MIB          QEMU guest RAM (default: 4096)
#   --cpus N              QEMU guest vCPUs (default: 4)
#   --no-kvm              Force TCG even if /dev/kvm is available
#                         (CI on free runners: KVM works; nested VMs: no)
#   --keep-vm             Leave the QEMU instance running after exit (for
#                         debugging — use `socat - UNIX-CONNECT:<output>/monitor.sock`
#                         to drive it)
#
# Exit codes:
#   0  success
#   1  generic failure (see serial log)
#   2  readiness marker not seen within --timeout
#   3  kickstart install failed
#   4  installed system did not boot
#   5  SSH check failed
#   77 missing dependency (qemu, ovmf, etc.) — distinguishable for CI skip

set -euo pipefail

# ── Argument parsing ────────────────────────────────────────────────────────

ISO_PATH=""
KICKSTART=""
MODE="ready" # ready | kickstart | ssh
TIMEOUT=300
OUTPUT_DIR="./iso-e2e-out"
MEMORY=4096
CPUS=4
NO_KVM=0
KEEP_VM=0

while [[ $# -gt 0 ]]; do
	case "$1" in
	--kickstart)
		MODE="kickstart"
		KICKSTART="$2"
		shift 2
		;;
	--ssh-only)
		MODE="ssh"
		shift
		;;
	--timeout)
		TIMEOUT="$2"
		shift 2
		;;
	--output)
		OUTPUT_DIR="$2"
		shift 2
		;;
	--memory)
		MEMORY="$2"
		shift 2
		;;
	--cpus)
		CPUS="$2"
		shift 2
		;;
	--no-kvm)
		NO_KVM=1
		shift
		;;
	--keep-vm)
		KEEP_VM=1
		shift
		;;
	-h | --help)
		sed -n '2,40p' "$0"
		exit 0
		;;
	-*)
		echo "Unknown flag: $1" >&2
		exit 1
		;;
	*)
		if [[ -z "$ISO_PATH" ]]; then
			ISO_PATH="$1"
		else
			echo "Unexpected positional arg: $1" >&2
			exit 1
		fi
		shift
		;;
	esac
done

if [[ -z "$ISO_PATH" ]]; then
	echo "Usage: $0 <iso_path> [--kickstart KS] [--ssh-only] [options]" >&2
	exit 1
fi

if [[ ! -f "$ISO_PATH" ]]; then
	echo "ISO not found: $ISO_PATH" >&2
	exit 1
fi
ISO_PATH="$(realpath "$ISO_PATH")"

if [[ "$MODE" == "kickstart" ]] && [[ ! -f "$KICKSTART" ]]; then
	echo "Kickstart file not found: $KICKSTART" >&2
	exit 1
fi
[[ "$MODE" == "kickstart" ]] && KICKSTART="$(realpath "$KICKSTART")"

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(realpath "$OUTPUT_DIR")"

# ── Dependency resolution ───────────────────────────────────────────────────

# Pick a QEMU binary. Order: distro qemu-kvm → qemu-system-x86_64 → brew.
QEMU=""
for candidate in /usr/libexec/qemu-kvm /usr/bin/qemu-kvm /usr/bin/qemu-system-x86_64 /home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64; do
	if [[ -x "$candidate" ]]; then
		QEMU="$candidate"
		break
	fi
done
if [[ -z "$QEMU" ]]; then
	echo "ERROR: no qemu-kvm / qemu-system-x86_64 found" >&2
	exit 77
fi

# Locate OVMF firmware. Path varies across distros (Debian/Ubuntu, Fedora,
# RHEL, Brew). We also need a writable copy of OVMF_VARS for UEFI to persist
# its NVRAM during boot.
OVMF_CODE=""
for f in \
	/usr/share/OVMF/OVMF_CODE_4M.fd \
	/usr/share/OVMF/OVMF_CODE.fd \
	/usr/share/edk2/ovmf/OVMF_CODE.fd \
	/usr/share/edk2-ovmf/x64/OVMF_CODE.fd \
	/usr/share/ovmf/OVMF.fd \
	/home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-code.fd; do
	if [[ -f "$f" ]]; then
		OVMF_CODE="$f"
		break
	fi
done
OVMF_VARS_SRC=""
for f in \
	/usr/share/OVMF/OVMF_VARS_4M.fd \
	/usr/share/OVMF/OVMF_VARS.fd \
	/usr/share/edk2/ovmf/OVMF_VARS.fd \
	/usr/share/edk2-ovmf/x64/OVMF_VARS.fd; do
	if [[ -f "$f" ]]; then
		OVMF_VARS_SRC="$f"
		break
	fi
done
if [[ -z "$OVMF_CODE" ]]; then
	echo "ERROR: OVMF firmware not found — install edk2-ovmf or ovmf" >&2
	exit 77
fi

# Decide on acceleration. /dev/kvm requires both presence and the calling
# user having r/w on it. Some CI runners gate KVM behind a sysctl + cgroup
# config that succeeds on access check but blocks at instantiation, so we
# allow --no-kvm to fall back to TCG.
ACCEL="tcg"
if [[ "$NO_KVM" -eq 0 ]] && [[ -r /dev/kvm ]] && [[ -w /dev/kvm ]]; then
	ACCEL="kvm"
fi
CPU_ARG="qemu64"
if [[ "$ACCEL" == "kvm" ]]; then
	CPU_ARG="host"
else
	# TCG: use Nehalem CPU model which is more stable with QEMU UEFI
	CPU_ARG="Nehalem"
fi

# ── Per-run scratch files ───────────────────────────────────────────────────

OVMF_VARS="${OUTPUT_DIR}/OVMF_VARS.fd"
MONITOR_SOCK="${OUTPUT_DIR}/monitor.sock"
SERIAL_LOG="${OUTPUT_DIR}/serial.log"
INSTALL_DISK="${OUTPUT_DIR}/install-disk.qcow2"
QEMU_PIDFILE="${OUTPUT_DIR}/qemu.pid"

# Fresh OVMF NVRAM each run — UEFI writes state during install (boot order,
# secure-boot vars). Reusing a stale one masks regressions.
if [[ -n "$OVMF_VARS_SRC" ]]; then
	cp -f "$OVMF_VARS_SRC" "$OVMF_VARS"
else
	# Some packaging only ships a combined OVMF.fd; create empty vars file
	# as a fallback (UEFI will populate it).
	truncate -s 4M "$OVMF_VARS"
fi
rm -f "$MONITOR_SOCK" "$SERIAL_LOG" "$QEMU_PIDFILE"

# ── Cleanup on exit ─────────────────────────────────────────────────────────

# shellcheck disable=SC2329  # invoked via `trap cleanup_vm EXIT`
cleanup_vm() {
	if [[ "$KEEP_VM" -eq 1 ]]; then
		echo "==> --keep-vm set; VM left running (monitor: ${MONITOR_SOCK})"
		return
	fi
	if [[ -f "$QEMU_PIDFILE" ]]; then
		local pid
		pid=$(cat "$QEMU_PIDFILE" 2>/dev/null || true)
		if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
			# Polite shutdown first; SIGKILL after 5s if still alive.
			if [[ -S "$MONITOR_SOCK" ]] && command -v socat &>/dev/null; then
				echo "system_powerdown" | socat - "UNIX-CONNECT:${MONITOR_SOCK}" 2>/dev/null || true
				sleep 5
			fi
			kill -TERM "$pid" 2>/dev/null || true
			sleep 2
			kill -KILL "$pid" 2>/dev/null || true
		fi
	fi
}
trap cleanup_vm EXIT

# ── Boot the live ISO ───────────────────────────────────────────────────────

boot_live_iso() {
	# qemu-img lives in the qemu-utils Debian/Ubuntu package, which the
	# `qemu-system-x86` package depends on only as Recommends. If the
	# workflow's apt install line forgets it, every diagnostic ends up
	# baffling ("QEMU failed to daemonize" with no further detail).
	# Surface the missing-binary case before we try to use it.
	if ! command -v qemu-img &>/dev/null; then
		echo "ERROR: qemu-img not found (install qemu-utils on Debian/Ubuntu)" >&2
		return 77
	fi
	# Create install disk on first call; reuse if exists (kickstart path).
	if [[ ! -f "$INSTALL_DISK" ]]; then
		echo "==> Creating 32G install disk: ${INSTALL_DISK}"
		if ! qemu-img create -f qcow2 "$INSTALL_DISK" 32G; then
			echo "ERROR: qemu-img create failed" >&2
			return 1
		fi
	fi

	# Kernel cmdline override: append `console=ttyS0` so the live env's
	# tunaos-live-ready.service marker reaches the serial log. We do this
	# via the OVMF boot menu's cmdline editing path, which the ISO's
	# grub.cfg accepts via the standard "e" key — but in unattended mode
	# we instead rely on the ISO's default cmdline already enabling
	# console=ttyS0 (livesys-config does this in upstream).

	echo "==> Booting ISO: ${ISO_PATH}"
	echo "==> Accel: ${ACCEL}, CPU: ${CPU_ARG}, MEM: ${MEMORY}M, CPUS: ${CPUS}"

	"$QEMU" \
		-name "tunaos-iso-e2e" \
		-machine q35 \
		-cpu "$CPU_ARG" \
		-accel "$ACCEL" \
		-m "$MEMORY" \
		-smp "$CPUS" \
		-drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}" \
		-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
		-drive "if=none,id=iso,file=${ISO_PATH},media=cdrom,readonly=on,format=raw" \
		-device virtio-scsi-pci,id=scsi \
		-device scsi-cd,drive=iso \
		-drive "if=none,id=disk,file=${INSTALL_DISK},format=qcow2" \
		-device virtio-blk-pci,drive=disk \
		-netdev "user,id=net0,hostfwd=tcp::2222-:22" \
		-device virtio-net-pci,netdev=net0 \
		-monitor "unix:${MONITOR_SOCK},server,nowait" \
		-serial "file:${SERIAL_LOG}" \
		-display none \
		-pidfile "$QEMU_PIDFILE" \
		-daemonize

	# Daemonized launch writes the pidfile then returns. Confirm.
	for _ in $(seq 1 30); do
		if [[ -s "$QEMU_PIDFILE" ]] && kill -0 "$(cat "$QEMU_PIDFILE")" 2>/dev/null; then
			echo "==> QEMU pid=$(cat "$QEMU_PIDFILE")"
			return 0
		fi
		sleep 1
	done
	echo "ERROR: QEMU failed to daemonize" >&2
	return 1
}

# Take a screenshot via QEMU monitor. Best-effort.
screenshot() {
	local label="$1"
	local out="${OUTPUT_DIR}/${label}.ppm"
	if [[ -S "$MONITOR_SOCK" ]] && command -v socat &>/dev/null; then
		echo "screendump ${out}" | socat - "UNIX-CONNECT:${MONITOR_SOCK}" >/dev/null 2>&1 || true
		[[ -f "$out" ]] && echo "==> Screenshot saved: ${out}"
	fi
}

# Wait for the live env to print its readiness marker.
wait_for_ready() {
	local deadline=$(($(date +%s) + TIMEOUT))
	local last_size=0
	echo "==> Waiting up to ${TIMEOUT}s for TUNAOS_LIVE_READY..."
	while (($(date +%s) < deadline)); do
		if [[ -f "$SERIAL_LOG" ]] && grep -q "TUNAOS_LIVE_READY" "$SERIAL_LOG" 2>/dev/null; then
			echo "==> Readiness marker found"
			return 0
		fi
		# Periodic progress: print serial-log size growth so a CI viewer
		# knows the VM is making forward progress vs. hung.
		local now_size=0
		[[ -f "$SERIAL_LOG" ]] && now_size=$(stat -c%s "$SERIAL_LOG" 2>/dev/null || echo 0)
		if [[ "$now_size" -ne "$last_size" ]]; then
			echo "    [serial: ${now_size} bytes]"
			last_size="$now_size"
		fi
		sleep 5
	done
	echo "ERROR: readiness marker not seen within ${TIMEOUT}s" >&2
	echo "--- last 50 lines of serial log ---" >&2
	tail -50 "$SERIAL_LOG" 2>/dev/null >&2 || true
	return 2
}

# Verify SSH connectivity. ISO must have ENABLE_SSHD=1.
check_ssh() {
	if ! command -v sshpass &>/dev/null; then
		echo "ERROR: sshpass required for --ssh-only; install it" >&2
		return 77
	fi
	local opts="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"
	# shellcheck disable=SC2086
	if sshpass -p live ssh $opts liveuser@127.0.0.1 -p 2222 true 2>/dev/null; then
		echo "==> SSH OK"
		return 0
	fi
	echo "ERROR: SSH check failed" >&2
	return 5
}

# Drive an Anaconda kickstart install. We don't (yet) interact with the
# install — we let it run unattended and watch for completion via serial
# log markers ("post-installation" / "reboot").
run_kickstart() {
	echo "==> Kickstart mode not yet implemented in $0"
	echo "    Stub: would copy ${KICKSTART} to a virtual floppy, append"
	echo "    inst.ks=hd:fd0 to the kernel cmdline, then watch for"
	echo "    /var/log/anaconda completion."
	# Returning 3 signals "kickstart path planned but not implemented" —
	# CI workflow can gate on this exit code to skip until done.
	return 3
}

# ── Main ────────────────────────────────────────────────────────────────────

case "$MODE" in
ready)
	boot_live_iso || exit 1
	sleep 5
	screenshot "00-boot"
	wait_for_ready
	rc=$?
	screenshot "10-ready"
	exit "$rc"
	;;
ssh)
	boot_live_iso || exit 1
	wait_for_ready || exit $?
	# Give sshd a moment to come up after the readiness marker.
	for _ in $(seq 1 15); do
		check_ssh && break
		sleep 2
	done
	check_ssh
	rc=$?
	screenshot "20-ssh"
	exit "$rc"
	;;
kickstart)
	boot_live_iso || exit 1
	wait_for_ready || exit $?
	screenshot "10-ready"
	run_kickstart
	exit $?
	;;
*)
	echo "Unknown mode: $MODE" >&2
	exit 1
	;;
esac
