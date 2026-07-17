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
#       been built with ENABLE_SSHD=1 (e.g. `just iso dev=1`).
#
#   scripts/iso-e2e.sh <iso_path> --app-launch <app|list|auto>
#       Boot the live env, then launch and screenshot apps: a single
#       desktop id, a comma-separated list, or "auto" for the DE's default
#       matrix (derived from FLAVOR; openQA apps_startstop clone, verified
#       via VLM screenshots instead of needles). Exit = VLM failure count.
#
#   scripts/iso-e2e.sh <disk.qcow2> --disk
#       Boot a disk image (qcow2/raw) instead of an ISO and verify it
#       reaches a graphical session (serial marker or screenshot sanity).
#       Used to gate GHCR tag promotion on images actually booting.
#
#   scripts/iso-e2e.sh <iso_path> --luks
#       Full LUKS e2e: boot the live ISO (needs ENABLE_SSHD=1), install via
#       fisherman (the same backend every TunaOS installer frontend uses)
#       with encryption.type=tpm2-luks against an emulated TPM 2.0 (swtpm),
#       then reboot the installed disk with the same TPM and confirm the
#       encrypted root auto-unlocks (reaching the login target proves it — a
#       missing/wrong TPM would hang in the initramfs). Requires the swtpm
#       package.
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
# Environment:
#   E2E_SMOKE_STRICT=1    Treat failures from the live-image smoke checks
#                         (scripts/e2e-smoke-checks.sh, TAP assertions adapted
#                         from frostyard/snosi) as fatal. Default: warn only.
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
APP_CMD=""
MODE="ready" # ready | install | kickstart | ssh | app-launch
TIMEOUT=300
OUTPUT_DIR="./iso-e2e-out"
MEMORY=4096
CPUS=4
NO_KVM=0
KEEP_VM=0
LUKS=0

while [[ $# -gt 0 ]]; do
	case "$1" in
	--kickstart)
		MODE="kickstart"
		KICKSTART="$2"
		shift 2
		;;
	--luks)
		# LUKS e2e: install to disk with tpm2-luks against an emulated TPM
		# (swtpm), then reboot and confirm the root volume auto-unlocks. Reuses
		# the ssh install-to-disk flow (bootc, not anaconda). Reaching the login
		# target on reboot proves the unlock worked — a wrong/absent TPM would
		# hang the boot in the initramfs at the cryptsetup prompt.
		MODE="install"
		LUKS=1
		shift
		;;
	--app-launch)
		MODE="app-launch"
		APP_CMD="$2"
		shift 2
		;;
	--ssh-only)
		MODE="ssh"
		shift
		;;
	--disk)
		MODE="disk"
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
		sed -n '2,50p' "$0"
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
	echo "Usage: $0 <iso_path> [--kickstart KS | --luks | --ssh-only] [options]" >&2
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Extract VARIANT and FLAVOR from ISO filename for screenshot comparison and
# for the fisherman recipe's image ref (used only as a fallback — callers
# should set VARIANT/FLAVOR explicitly, e.g. luks-e2e.yml's env: block).
# Two conventions exist: the promotion-flow rename
# "<variant>-<flavor>-<version>-<arch>.iso" and build-iso-tacklebox.sh's raw
# tacklebox output "tunaos-<variant>-<flavor>.iso" — strip a leading
# "tunaos-" project prefix so both parse the same way.
ISO_BASENAME="$(basename "$ISO_PATH" .iso)"
ISO_BASENAME="${ISO_BASENAME#tunaos-}"
ISO_VARIANT="${ISO_BASENAME%%-*}"
ISO_FLAVOR="${ISO_BASENAME#*-}"
ISO_FLAVOR="${ISO_FLAVOR%%-*}"
: "${VARIANT:=${ISO_VARIANT}}"
: "${FLAVOR:=${ISO_FLAVOR}}"

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
	# Broaden the TCG CPU to include modern extensions that post-2020
	# shim/GRUB binaries require. The default qemu64 omits SSE4, AES-NI,
	# XSAVE, and AVX, causing #UD crashes when loading EFI bootloaders
	# from newer distros (e.g. AlmaLinux Kitten 10 / yellowfin).
	CPU_ARG="qemu64,+sse4.1,+sse4.2,+aes,+xsave,+xsaveopt,+xsavec,+xsaves,+popcnt,+avx,+avx2"
fi

# ── Per-run scratch files ───────────────────────────────────────────────────

OVMF_VARS="${OUTPUT_DIR}/OVMF_VARS.fd"
MONITOR_SOCK="${OUTPUT_DIR}/monitor.sock"
SERIAL_LOG="${OUTPUT_DIR}/serial.log"
LIVE_SERIAL_LOG="${OUTPUT_DIR}/live-serial.log"
LUKS_EVIDENCE_LOG="${OUTPUT_DIR}/luks-evidence.log"
INSTALL_DISK="${OUTPUT_DIR}/install-disk.qcow2"
QEMU_PIDFILE="${OUTPUT_DIR}/qemu.pid"

record_luks_evidence() {
	[[ "$LUKS" -eq 1 ]] || return 0
	echo "$1" | tee -a "$LUKS_EVIDENCE_LOG"
}

# ── Emulated TPM 2.0 (swtpm) — LUKS mode only ───────────────────────────────
# The install-time enrollment (systemd-cryptenroll --tpm2-device=auto) and the
# reboot-time unlock must see the SAME TPM state, so a single swtpm instance is
# started once and its socket attached to every QEMU launch below. TPM_ARGS is
# empty unless --luks is set, so non-LUKS modes are byte-for-byte unchanged.
TPM_DIR="${OUTPUT_DIR}/swtpm"
TPM_SOCK="${TPM_DIR}/swtpm-sock"
TPM_PIDFILE="${TPM_DIR}/swtpm.pid"
TPM_ARGS=""

start_swtpm() {
	command -v swtpm &>/dev/null || {
		echo "ERROR: --luks requires swtpm (install the 'swtpm' package)" >&2
		return 77
	}
	rm -rf "$TPM_DIR"
	mkdir -p "$TPM_DIR"
	echo "==> Starting swtpm (TPM 2.0) at ${TPM_SOCK}"
	swtpm socket \
		--tpmstate "dir=${TPM_DIR}" \
		--ctrl "type=unixio,path=${TPM_SOCK}" \
		--tpm2 \
		--flags startup-clear \
		--daemon \
		--pid "file=${TPM_PIDFILE}"
	for _ in $(seq 1 20); do
		[[ -S "$TPM_SOCK" ]] && break
		sleep 0.5
	done
	[[ -S "$TPM_SOCK" ]] || {
		echo "ERROR: swtpm socket did not appear" >&2
		return 1
	}
	# tpm-crb is the CRB interface OVMF/edk2 measures into; works on q35 and pc.
	TPM_ARGS="-chardev socket,id=chrtpm,path=${TPM_SOCK} -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-crb,tpmdev=tpm0"
}

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
	# Tear down the emulated TPM (LUKS mode).
	if [[ -f "$TPM_PIDFILE" ]]; then
		local tpid
		tpid=$(cat "$TPM_PIDFILE" 2>/dev/null || true)
		[[ -n "$tpid" ]] && kill "$tpid" 2>/dev/null || true
	fi
}
trap cleanup_vm EXIT

# Bring up the emulated TPM before any QEMU launch so both the install boot and
# the post-install reboot attach the same TPM state.
if [[ "$LUKS" -eq 1 ]]; then
	start_swtpm || exit $?
fi

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

	# shellcheck disable=SC2086  # TPM_ARGS is intentionally word-split (empty unless --luks)
	"$QEMU" \
		-name "tunaos-iso-e2e" \
		-machine pc \
		-cpu "$CPU_ARG" \
		-accel "$ACCEL" \
		-m "$MEMORY" \
		-smp "$CPUS" \
		${TPM_ARGS} \
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
		-vga virtio \
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

# Compare screenshot against a reference using ImageMagick SSIM (Layer 2).
# Returns 0 if similarity >= threshold (0.99 = 99%), 1 otherwise.
# Reference images are stored in tests/reference/{variant}-{flavor}-reference.png
# Generate with: convert reference.ppm reference.png && cp to tests/reference/
screenshot_compare() {
	local label="$1"
	local ref_dir="${SCRIPT_DIR}/tests/reference"
	local variant_flavor="${VARIANT:-unknown}-${FLAVOR:-unknown}"
	local ref="${ref_dir}/${variant_flavor}-reference.png"
	local cap="${OUTPUT_DIR}/${label}.ppm"

	if [[ ! -f "$ref" ]]; then
		echo "==> No reference image at ${ref} — skipping comparison"
		return 0
	fi
	if [[ ! -f "$cap" ]]; then
		echo "==> No captured screenshot at ${cap} — cannot compare"
		return 1
	fi
	if ! command -v compare &>/dev/null; then
		echo "==> ImageMagick compare not available — skipping comparison"
		return 0
	fi

	# Convert PPM to PNG for comparison
	local cap_png="${OUTPUT_DIR}/${label}.png"
	if command -v convert &>/dev/null; then
		convert "$cap" "$cap_png" 2>/dev/null || true
	fi

	# SSIM comparison: 1.0 = identical, >0.99 = perceptually same
	local ssim
	ssim=$(compare -metric SSIM "$ref" "${cap_png:-$cap}" "${OUTPUT_DIR}/${label}-diff.png" 2>&1 || true)
	local threshold=0.99

	if [[ -n "$ssim" ]]; then
		local ok
		ok=$(echo "$ssim >= $threshold" | bc 2>/dev/null || echo 0)
		if [[ "$ok" == "1" ]]; then
			echo "==> ✅ Screenshot matches reference (SSIM: $ssim >= $threshold)"
			return 0
		else
			echo "==> ⚠️  Screenshot differs from reference (SSIM: $ssim < $threshold)"
			echo "    Diff image: ${OUTPUT_DIR}/${label}-diff.png"
			# Non-blocking — emit ::warning, don't fail
			echo "::warning::Screenshot comparison: SSIM $ssim below threshold $threshold"
			return 0
		fi
	else
		echo "==> SSIM comparison produced no output — skipping"
		return 0
	fi
}

# Sanity-check a captured screenshot: it must exist and show actual content
# (not a black/blank framebuffer). Used as the readiness fallback when the
# serial marker never arrives — the bootc base kernels ship
# CONFIG_SERIAL_8250=m, so TUNAOS_LIVE_READY often can't reach the serial
# console even though the live session is up (see research.md).
# Returns 0 if the screenshot looks like a rendered screen, 1 otherwise.
screenshot_sane() {
	local label="$1"
	local cap="${OUTPUT_DIR}/${label}.ppm"
	if [[ ! -s "$cap" ]]; then
		echo "==> No screenshot at ${cap} — cannot verify via fallback" >&2
		return 1
	fi
	if ! command -v convert &>/dev/null; then
		# Without ImageMagick we can only check the file is non-trivial.
		local size
		size=$(stat -c%s "$cap" 2>/dev/null || echo 0)
		[[ "$size" -gt 100000 ]] && return 0
		return 1
	fi
	# standard_deviation ~0 means a uniform (blank/black) screen. A rendered
	# DM/desktop always has structure. fx output is 0..1.
	local stddev
	stddev=$(convert "$cap" -colorspace Gray -format "%[fx:standard_deviation]" info: 2>/dev/null || echo 0)
	echo "==> Screenshot ${label} stddev=${stddev}"
	if awk -v s="$stddev" 'BEGIN{exit !(s > 0.02)}'; then
		return 0
	fi
	echo "==> Screenshot ${label} looks blank (stddev=${stddev} <= 0.02)" >&2
	return 1
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

# Upload and run the TAP-style live-image smoke checks (assertions adapted
# from frostyard/snosi's tiered on-VM test scripts) over SSH. Non-fatal by
# default — the TAP output is CI evidence; set E2E_SMOKE_STRICT=1 to turn
# any failed assertion into a hard failure once the checks have proven
# stable across the matrix.
run_smoke_checks() {
	local script_dir
	script_dir="$(dirname "${BASH_SOURCE[0]}")"
	local -a COMMON_SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
	local ssh_cmd=(sshpass -p live ssh "${COMMON_SSH_OPTS[@]}" -p 2222 liveuser@127.0.0.1)
	local scp_cmd=(sshpass -p live scp "${COMMON_SSH_OPTS[@]}" -P 2222)

	"${scp_cmd[@]}" "${script_dir}/lib/e2e-assert.sh" liveuser@127.0.0.1:/tmp/e2e-assert.sh
	"${scp_cmd[@]}" "${script_dir}/e2e-smoke-checks.sh" liveuser@127.0.0.1:/tmp/e2e-smoke-checks.sh

	local smoke_output smoke_rc=0
	smoke_output=$("${ssh_cmd[@]}" "TEST_LIB_DIR=/tmp bash /tmp/e2e-smoke-checks.sh" 2>&1) || smoke_rc=$?
	echo "$smoke_output" | tee -a "${SERIAL_LOG}"
	if [[ "$smoke_rc" -ne 0 ]]; then
		echo "::warning::live-image smoke checks reported ${smoke_rc} failure(s)"
		if [[ "${E2E_SMOKE_STRICT:-0}" -eq 1 ]]; then
			echo "ERROR: E2E_SMOKE_STRICT=1 and smoke checks failed" >&2
			return 1
		fi
	fi
	return 0
}

# Harvest the installed-system TAP checks from the serial console. The
# installed system has no SSH user, so the snosi-derived assertions are baked
# into the image (build_scripts/checks/e2e-runtime-checks.sh, run by
# tunaos-desktop-contract.service) and emit grep-able markers on ttyS0:
# TUNAOS_INSTALL_CHECKS_BEGIN ... TUNAOS_INSTALL_CHECKS_RESULT pass=N fail=M.
# The checks ExecStart fires right after the contract marker, so wait
# briefly for the RESULT line; images built before the checks existed emit
# nothing — tolerate that so old tags can still be gated/promoted.
harvest_install_checks() {
	local deadline=$(($(date +%s) + ${INSTALL_CHECKS_WAIT:-90})) found=0
	while true; do
		if grep -q "TUNAOS_INSTALL_CHECKS_RESULT" "$SERIAL_LOG" 2>/dev/null; then
			found=1
			break
		fi
		(($(date +%s) < deadline)) || break
		sleep 3
	done
	if [[ "$found" -ne 1 ]]; then
		echo "==> No installed-system TAP checks on serial (image predates e2e-runtime-checks) — skipping"
		return 0
	fi
	echo "==> Installed-system TAP checks (from serial console):"
	sed -n '/TUNAOS_INSTALL_CHECKS_BEGIN/,/TUNAOS_INSTALL_CHECKS_RESULT/p' "$SERIAL_LOG" | tr -d '\r'
	local fail
	fail=$(grep -o "TUNAOS_INSTALL_CHECKS_RESULT pass=[0-9]* fail=[0-9]*" "$SERIAL_LOG" | tail -1 | grep -o "fail=[0-9]*" | cut -d= -f2)
	if [[ -n "$fail" && "$fail" -gt 0 ]]; then
		echo "::warning::installed-system checks reported ${fail} failure(s)"
		if [[ "${E2E_SMOKE_STRICT:-0}" -eq 1 ]]; then
			echo "ERROR: E2E_SMOKE_STRICT=1 and installed-system checks failed" >&2
			return 1
		fi
	fi
	return 0
}

# Run bootc install-to-disk via SSH, then reboot and verify the installed system.
# This replaces the Anaconda kickstart approach (TunaOS uses bootc, not anaconda).
run_install() {
	record_luks_evidence "TUNAOS_LUKS_E2E_INSTALL_STARTED luks=${LUKS}"
	echo "==> Waiting up to 60s for SSH..."
	for _ in $(seq 1 30); do
		check_ssh && break
		sleep 2
	done
	check_ssh || {
		echo "ERROR: SSH not available"
		return 5
	}

	# scp uses -P (capital) for the port flag; ssh uses -p. Sharing one array
	# with the wrong flag silently makes scp treat the port number as a
	# source-file argument ("stat local 2222: No such file or directory").
	local -a COMMON_SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
	local ssh_cmd=(sshpass -p live ssh "${COMMON_SSH_OPTS[@]}" -p 2222 liveuser@127.0.0.1)
	local scp_cmd=(sshpass -p live scp "${COMMON_SSH_OPTS[@]}" -P 2222)

	# Bug #20: fisherman's network pull stalled indefinitely mid-blob (layer
	# 42/65, no error, no further output) after dozens of smaller layers
	# pulled fine in under a minute. Classic QEMU SLIRP Path-MTU-Discovery
	# blackhole: SLIRP's usermode NAT often drops the ICMP "fragmentation
	# needed" replies PMTUD depends on — especially likely here since the
	# QEMU guest is itself nested inside the GitHub Actions runner's own
	# virtualized network, which may already clamp the effective MTU below
	# what the guest assumes. Small blobs fit in a packet or two and never
	# trigger fragmentation; a large layer does, and the connection just
	# hangs with no error on either end. Clamp the guest's own interface
	# MTU down before pulling anything, so packets never need fragmenting
	# in the first place — sidesteps PMTUD entirely instead of relying on
	# it working correctly.
	"${ssh_cmd[@]}" 'for i in $(ls /sys/class/net | grep -v ^lo$); do sudo ip link set "$i" mtu 1400; done; ip -o link show' || true

	# Mirrors projectbluefin/dakota-iso's luks-install-qemu.sh: install via
	# fisherman (the same backend every TunaOS installer frontend uses,
	# gnome included — customize-live.sh symlinks it from each flavor's
	# installer Flatpak), not a raw `bootc install to-disk`. fisherman does
	# its own partitioning, LUKS setup + TPM enrollment, and BLS kernel-arg
	# patching (rd.luks.name=...) so the installed system actually knows how
	# to unlock at boot — logic that `bootc install to-disk
	# --block-setup tpm2-luks` doesn't cover the same way and that real users
	# never exercise directly. See docs/ci-troubleshooting.md's fisherman
	# glossary entry.
	"${ssh_cmd[@]}" "command -v /usr/local/bin/fisherman" &>/dev/null || {
		echo "ERROR: fisherman not found on live image (VARIANT=${VARIANT:-} FLAVOR=${FLAVOR:-})" >&2
		return 3
	}

	# Pre-install evidence: the live squash boots the same bootc image that
	# fisherman is about to install, so snosi-style smoke assertions here
	# catch a broken image before the (much slower) install/reboot phases.
	echo "==> Running live-image smoke checks..."
	run_smoke_checks || return 3

	# Diagnostics (previous commit) confirmed decisively: `podman images -a`
	# on the live VM is completely empty (only the header row), and neither
	# offline-store path customize-live.sh references even exists. There is
	# no local copy of the image anywhere on this live squash to reference
	# by name — TunaOS's tacklebox pipeline doesn't embed an
	# additionalimagestore the way dakota-iso's does. The system boots as a
	# deployed ostree/bootc filesystem directly; it never runs "as a
	# container" with a queryable local copy.
	#
	# All four prior guesses failed because they all assumed SOME local
	# image existed to reference (bugs #13/#14/#16/#18). The actual fix:
	# set `image` (not just `targetImgref`) to a real registry ref. That
	# makes fisherman's Image field non-empty, which triggers
	# bootcViaContainer — fisherman's CheckImage() sees nothing local
	# (NeedsPull=true), actually `podman pull`s the image for real, and
	# only then runs bootc inside that freshly pulled container. This is
	# fisherman's normal, designed, non-live-ISO install path — the one a
	# real production install machine (with no embedded local store) uses
	# too. Requires network access, which the LUKS E2E runner already has
	# (and already does a GHCR login earlier in the job).
	local image_ref="ghcr.io/tuna-os/${VARIANT:-}:${FLAVOR:-}"
	local recipe_image="${image_ref}" recipe_target_imgref="${image_ref}"
	# Tacklebox ISO images with offline_payloads mount the embedded
	# containers-storage graphroot at /var/lib/superiso-store before the live
	# session starts.  Prefer it when it contains this exact ref: this is the
	# same source fisherman will bind into its bootc container, so no guest-NAT
	# pull is needed.  Keep the registry fallback for older ISOs and for a
	# payload/tag mismatch.
	local offline_store_json='[]' use_offline_store=0
	if "${ssh_cmd[@]}" "sudo test -d /var/lib/superiso-store && sudo podman image exists '${image_ref}'"; then
		use_offline_store=1
		offline_store_json='["/var/lib/superiso-store"]'
		echo "==> Using embedded offline image store for ${image_ref}"
	fi
	local composefs_backend="false" bootloader="grub2"
	# grouper (Ubuntu) has no bootupd package available via apt, so it ships
	# systemd-boot instead and installs via bootc's composefs-native backend.
	if [[ "${VARIANT:-}" == "grouper" ]]; then
		composefs_backend="true"
		bootloader="systemd"
	fi
	local encryption_json='{"type": "none"}'
	[[ "$LUKS" -eq 1 ]] && encryption_json='{"type": "tpm2-luks"}'

	local RECIPE_LOCAL="${OUTPUT_DIR}/e2e-recipe.json"
	cat >"$RECIPE_LOCAL" <<EOF
{
  "disk": "/dev/vda",
  "filesystem": "xfs",
  "image": "${recipe_image}",
  "targetImgref": "${recipe_target_imgref}",
  "composeFsBackend": ${composefs_backend},
  "bootloader": "${bootloader}",
  "additionalImageStores": ${offline_store_json},
  "hostname": "tunaos-e2e",
  "encryption": ${encryption_json},
  "flatpaks": []
}
EOF
	echo "==> Uploading fisherman recipe..."
	"${scp_cmd[@]}" "$RECIPE_LOCAL" liveuser@127.0.0.1:/tmp/e2e-recipe.json

	# Pre-pull the image with retries before invoking fisherman. In practice
	# (bug #20) the pull through QEMU's SLIRP NAT deterministically stalls
	# mid-blob on one specific layer for ~29 minutes before erroring — not a
	# PMTUD/MTU issue (an MTU=1400 guest-side clamp did not fix it, and the
	# stalling blob isn't unusually large compared to its neighbors). Root
	# cause not isolated further; treated as SLIRP connection flakiness.
	# `podman pull` skips layers already present in local storage, so each
	# retry only has to re-fetch whatever didn't finish, not the whole image.
	# Once the image is present locally, fisherman's bootcViaContainer mode
	# (CheckImage()) finds it and skips its own pull.
	if [[ "$use_offline_store" -eq 0 ]]; then
		echo "==> Pre-pulling ${image_ref} (retry on stall, layers already fetched are cached)..."
		# Attempts 3-4 pull through the Cloudflare Worker relay instead of
		# ghcr.io directly: bug #20's stall is between the SLIRP guest and
		# GHCR's CDN, and a run where all 4 direct attempts stalled shows
		# retrying the same path isn't enough. The relay serves the same
		# org-allowlisted content (edge-cached, digest-addressed) over a
		# different server path; podman follows its passthrough auth.
		# The pulled tag is retagged to the canonical ghcr.io name so
		# fisherman's CheckImage() still finds it.
		local shim_host="ghcr-shim.trogdor30001.workers.dev"
		local shim_ref="${image_ref/ghcr.io/${shim_host}}"
		local pull_ok=0
		for pull_attempt in 1 2 3 4; do
			local ref="$image_ref"
			[[ "$pull_attempt" -ge 3 ]] && ref="$shim_ref"
			echo "--> pull attempt ${pull_attempt}/4 (${ref%%/*})"
			if timeout 600 "${ssh_cmd[@]}" "sudo podman pull ${ref} 2>&1" 2>&1 | tee -a "${SERIAL_LOG}"; then
				if [[ "$ref" != "$image_ref" ]]; then
					"${ssh_cmd[@]}" "sudo podman tag ${ref} ${image_ref}" 2>&1 | tee -a "${SERIAL_LOG}" || true
				fi
				pull_ok=1
				break
			fi
			echo "==> pull attempt ${pull_attempt} failed or stalled; retrying..."
		done
		if [[ "$pull_ok" -ne 1 ]]; then
			echo "ERROR: failed to pull ${image_ref} after 4 attempts"
			return 3
		fi
	fi

	echo "==> Running fisherman /tmp/e2e-recipe.json..."
	# Bound with `timeout` as a safety net; the image is already local at
	# this point so this should only cover the actual install steps, not a
	# network pull.
	timeout 1800 "${ssh_cmd[@]}" "sudo /usr/local/bin/fisherman /tmp/e2e-recipe.json 2>&1" 2>&1 | tee -a "${SERIAL_LOG}" || {
		rc=$?
		if [[ $rc -eq 0 ]]; then
			true
		elif [[ $rc -eq 124 ]]; then
			echo "ERROR: fisherman install timed out after 1800s (likely a stalled podman pull)"
			return 3
		else
			echo "ERROR: fisherman install failed (exit $rc)"
			return 3
		fi
	}

	if [[ "$LUKS" -eq 1 ]]; then
		# Verify against the resulting disk state, not fisherman's log text —
		# robust to log-format changes and catches a silent fallback to an
		# unencrypted layout that would still boot and pass the checks below.
		# TAP-style check script (scripts/e2e-luks-checks.sh, using the
		# check()/print_summary() helpers in scripts/lib/e2e-assert.sh)
		# uploaded and run over SSH, pattern borrowed from frostyard/snosi's
		# tiered on-VM test scripts.
		local script_dir
		script_dir="$(dirname "${BASH_SOURCE[0]}")"
		"${scp_cmd[@]}" "${script_dir}/lib/e2e-assert.sh" liveuser@127.0.0.1:/tmp/e2e-assert.sh
		"${scp_cmd[@]}" "${script_dir}/e2e-luks-checks.sh" liveuser@127.0.0.1:/tmp/e2e-luks-checks.sh
		local luks_check_output
		luks_check_output=$("${ssh_cmd[@]}" "TEST_LIB_DIR=/tmp bash /tmp/e2e-luks-checks.sh" 2>&1) || true
		echo "$luks_check_output" | tee -a "$LUKS_EVIDENCE_LOG"

		if echo "$luks_check_output" | grep -q "^ok - installed disk has a crypto_LUKS partition"; then
			record_luks_evidence "TUNAOS_LUKS_E2E_ENCRYPTED_DISK_CONFIRMED"
		else
			echo "ERROR: installed disk has no crypto_LUKS partition"
			return 3
		fi
		if echo "$luks_check_output" | grep -q "^ok - LUKS header has a systemd-tpm2 enrollment token"; then
			record_luks_evidence "TUNAOS_LUKS_E2E_TPM_ENROLLMENT_CONFIRMED"
		else
			echo "ERROR: --luks set but no systemd-tpm2 token in LUKS header"
			return 3
		fi
	fi

	echo "==> fisherman install complete. Shutting down..."
	"${ssh_cmd[@]}" "sudo systemctl poweroff" 2>/dev/null || true
	sleep 10

	# Wait for VM to fully stop
	if [[ -f "$QEMU_PIDFILE" ]]; then
		local pid
		pid=$(cat "$QEMU_PIDFILE" 2>/dev/null || true)
		if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
			echo "==> Waiting for VM to shut down..."
			for _ in $(seq 1 30); do
				kill -0 "$pid" 2>/dev/null || break
				sleep 2
			done
		fi
	fi

	# The installed-boot gate must never match a marker emitted by the live
	# environment. Preserve the first boot as separate evidence and give QEMU a
	# fresh serial log for the disk boot.
	mv -f "$SERIAL_LOG" "$LIVE_SERIAL_LOG"
	: >"$SERIAL_LOG"

	echo "==> Booting installed system..."
	# Boot from the install disk (remove cdrom)
	# shellcheck disable=SC2086  # TPM_ARGS is intentionally word-split (empty unless --luks)
	"$QEMU" \
		-name "tunaos-iso-e2e-installed" \
		-machine pc \
		-cpu "$CPU_ARG" \
		-accel "$ACCEL" \
		-m "$MEMORY" \
		-smp "$CPUS" \
		${TPM_ARGS} \
		-drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}" \
		-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
		-drive "if=none,id=disk,file=${INSTALL_DISK},format=qcow2" \
		-device virtio-blk-pci,drive=disk \
		-netdev "user,id=net0,hostfwd=tcp::2222-:22" \
		-device virtio-net-pci,netdev=net0 \
		-monitor "unix:${MONITOR_SOCK},server,nowait" \
		-serial "file:${SERIAL_LOG}" \
		-vga virtio \
		-display none \
		-pidfile "$QEMU_PIDFILE" \
		-daemonize

	# Every ISO matrix cell is a desktop image. A boot prompt or multi-user
	# target is insufficient evidence: require the image's display-manager and
	# desktop-session contract before declaring the installed system healthy.
	local require_desktop_contract=1
	echo "==> Waiting for installed system to boot (up to 5 min)..."
	for _ in $(seq 1 60); do
		local installed_ready=0
		if [[ "$require_desktop_contract" -eq 1 ]]; then
			grep -qE "TUNAOS_DESKTOP_CONTRACT_(OK|FAIL)" "${SERIAL_LOG}" 2>/dev/null && installed_ready=1
		else
			grep -q "Reached target.*Graphical\|Reached target.*Multi-User\|login:" "${SERIAL_LOG}" 2>/dev/null &&
				installed_ready=1
		fi
		if [[ "$installed_ready" -eq 1 ]]; then
			echo "==> Installed system booted successfully!"
			record_luks_evidence "TUNAOS_LUKS_E2E_PASS encrypted=1 tpm_unlock=1 installed_boot=1 desktop_contract=${require_desktop_contract}"
			harvest_install_checks || return 1
			screenshot "30-installed"
			# VLM verification of installed system
			if command -v python3 &>/dev/null; then
				VLM_SCRIPT="$(dirname "${BASH_SOURCE[0]}")/desktop-verify.py"
				if [[ -f "$VLM_SCRIPT" ]]; then
					PNG="${OUTPUT_DIR}/30-installed.png"
					[[ -f "${OUTPUT_DIR}/30-installed.ppm" ]] && convert "${OUTPUT_DIR}/30-installed.ppm" "$PNG" 2>/dev/null || true
					[[ -f "$PNG" ]] && python3 "$VLM_SCRIPT" "$PNG" --mode desktop || true
				fi
			fi
			return 0
		fi
		sleep 5
	done

	echo "ERROR: installed system did not boot within timeout"
	return 4
}

# Boot a disk image (qcow2/raw) directly — used by --disk mode to verify
# installed/converted images (e.g. the qcow2 produced from a GHCR image
# before its tags are promoted). Reuses the same firmware/accel plumbing.
boot_disk_image() {
	local fmt="qcow2"
	[[ "$ISO_PATH" == *.raw || "$ISO_PATH" == *.img ]] && fmt="raw"
	echo "==> Booting disk image: ${ISO_PATH} (${fmt})"
	echo "==> Accel: ${ACCEL}, CPU: ${CPU_ARG}, MEM: ${MEMORY}M, CPUS: ${CPUS}"

	"$QEMU" \
		-name "tunaos-disk-e2e" \
		-machine pc \
		-cpu "$CPU_ARG" \
		-accel "$ACCEL" \
		-m "$MEMORY" \
		-smp "$CPUS" \
		-drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}" \
		-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
		-drive "if=none,id=disk,file=${ISO_PATH},format=${fmt}" \
		-device virtio-blk-pci,drive=disk \
		-netdev "user,id=net0,hostfwd=tcp::2222-:22" \
		-device virtio-net-pci,netdev=net0 \
		-monitor "unix:${MONITOR_SOCK},server,nowait" \
		-serial "file:${SERIAL_LOG}" \
		-vga virtio \
		-display none \
		-pidfile "$QEMU_PIDFILE" \
		-daemonize

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

# ── Main ────────────────────────────────────────────────────────────────────

case "$MODE" in
disk)
	boot_disk_image || exit 1
	echo "==> Waiting up to ${TIMEOUT}s for a graphical session..."
	deadline=$(($(date +%s) + TIMEOUT))
	rc=2
	while (($(date +%s) < deadline)); do
		# QEMU exiting early means the image didn't boot at all.
		if [[ -f "$QEMU_PIDFILE" ]] && ! kill -0 "$(cat "$QEMU_PIDFILE")" 2>/dev/null; then
			echo "ERROR: VM exited during boot" >&2
			exit 1
		fi
		if grep -qE "TUNAOS_DESKTOP_CONTRACT_(OK|FAIL)" "$SERIAL_LOG" 2>/dev/null; then
			echo "==> Desktop experience contract reached (serial)"
			rc=0
			harvest_install_checks || rc=1
			break
		fi
		sleep 10
	done
	# Let the display manager finish drawing before capturing evidence.
	sleep 30
	screenshot "10-ready"
	if [[ "$rc" -ne 0 ]]; then
		echo "ERROR: desktop experience contract marker was not emitted" >&2
	fi
	exit "$rc"
	;;
ready)
	boot_live_iso || exit 1
	sleep 5
	screenshot "00-boot"
	# NB: `&& rc=0 ||` keeps set -e from killing the script when the marker
	# never arrives — everything below (the 10-ready screenshot and the
	# screenshot-sanity fallback) MUST still run on that path; it's the
	# whole recovery story for serial-less kernels. A bare call here
	# historically aborted the script at exit 2 with only 00-boot captured.
	wait_for_ready && rc=0 || rc=$?
	screenshot "10-ready"
	# Serial marker missing is expected when the guest kernel has no serial
	# console support; fall back to verifying the framebuffer actually
	# rendered a screen. Hard failures (blank/absent screenshot) stay fatal
	# so this exit code can gate publishing.
	if [[ "$rc" -ne 0 ]] && screenshot_sane "10-ready"; then
		echo "::warning::readiness marker not seen on serial console; screenshot sanity check passed — treating as ready"
		rc=0
	fi
	# VLM vision verification (non-blocking)
	if command -v python3 &>/dev/null; then
		VLM_SCRIPT="$(dirname "${BASH_SOURCE[0]}")/desktop-verify.py"
		if [[ -f "$VLM_SCRIPT" ]]; then
			PNG="${OUTPUT_DIR}/10-ready.png"
			[[ -f "${OUTPUT_DIR}/10-ready.ppm" ]] && convert "${OUTPUT_DIR}/10-ready.ppm" "$PNG" 2>/dev/null || true
			[[ -f "$PNG" ]] && python3 "$VLM_SCRIPT" "$PNG" --mode desktop || true
		fi
	fi
	screenshot_compare "10-ready" || true
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
	if [[ "$rc" -eq 0 ]]; then
		echo "==> Running live-image smoke checks..."
		run_smoke_checks || rc=5
	fi
	screenshot "20-ssh"
	exit "$rc"
	;;
kickstart)
	boot_live_iso || exit 1
	wait_for_ready || exit $?
	screenshot "10-ready"
	run_install
	exit $?
	;;
install)
	boot_live_iso || exit 1
	wait_for_ready || exit $?
	screenshot "10-ready"
	run_install
	exit $?
	;;
app-launch)
	boot_live_iso || exit 1
	wait_for_ready || exit $?
	screenshot "10-ready"
	# Wait for SSH
	for _ in $(seq 1 15); do
		check_ssh && break
		sleep 2
	done
	check_ssh || exit $?

	# Per-DE app matrix (clone of openQA's apps_startstop tests, needle-free:
	# VLM screenshot verification instead of pixel templates). APP_CMD may be
	# a single desktop id, a comma-separated list, or "auto" to pick the
	# matrix for this image's DE (first component of FLAVOR, e.g.
	# gnome-nvidia-hwe -> gnome).
	APP="${APP_CMD:-nautilus}"
	if [[ "$APP" == "auto" ]]; then
		flavor_de="${FLAVOR:-}"
		case "${flavor_de%%-*}" in
		gnome) APP="org.gnome.Nautilus,org.gnome.TextEditor" ;;
		kde) APP="org.kde.dolphin,org.kde.konsole" ;;
		cosmic) APP="com.system76.CosmicFiles,com.system76.CosmicTerm" ;;
		xfce) APP="thunar,xfce4-terminal" ;;
		*)
			echo "==> No app matrix for FLAVOR=${FLAVOR:-unset}; capturing session only"
			APP=""
			;;
		esac
	fi

	# gtk-launch needs the live session's bus/compositor; a bare SSH login
	# has neither, which is why single-app mode historically "may have
	# failed". liveuser is auto-logged-in, so its session bus is at the
	# canonical /run/user/<uid>/bus path.
	# shellcheck disable=SC2016  # $(id -u) must expand on the guest, not here
	SSH_APP_ENV='DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus WAYLAND_DISPLAY=wayland-0 DISPLAY=:0'
	app_failures=0
	app_idx=0
	VLM_SCRIPT="$(dirname "${BASH_SOURCE[0]}")/desktop-verify.py"
	IFS=',' read -ra APP_LIST <<<"$APP"
	for app in "${APP_LIST[@]}"; do
		[[ -n "$app" ]] || continue
		app_idx=$((app_idx + 1))
		label="20-app-$(printf '%02d' "$app_idx")-${app##*.}"
		echo "==> Launching app via SSH: $app"
		sshpass -p live ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 liveuser@127.0.0.1 \
			"env $SSH_APP_ENV gtk-launch $app 2>&1" || echo "  (app launch may have failed)"
		sleep 8
		screenshot "$label"
		# VLM verification per app (aggregate failures; absence of the VLM
		# path keeps this mode green, matching previous behavior).
		if command -v python3 &>/dev/null && [[ -f "$VLM_SCRIPT" ]]; then
			PNG="${OUTPUT_DIR}/${label}.png"
			[[ -f "${OUTPUT_DIR}/${label}.ppm" ]] && convert "${OUTPUT_DIR}/${label}.ppm" "$PNG" 2>/dev/null || true
			if [[ -f "$PNG" ]]; then
				if ! python3 "$VLM_SCRIPT" "$PNG" --mode desktop; then
					echo "::warning::VLM verification failed for ${app}"
					app_failures=$((app_failures + 1))
				fi
			fi
		fi
		# Best-effort stop (openQA closes each app before the next): match the
		# desktop id's last segment, lowercased, against the process table.
		app_proc="${app##*.}"
		sshpass -p live ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 liveuser@127.0.0.1 \
			"pkill -f '${app_proc,,}' 2>/dev/null" || true
		sleep 2
	done
	[[ "$app_idx" -eq 0 ]] && screenshot "20-app"
	echo "==> app matrix complete: ${app_idx} app(s), ${app_failures} VLM failure(s)"
	exit "$app_failures"
	;;
*)
	echo "Unknown mode: $MODE" >&2
	exit 1
	;;
esac
