#!/usr/bin/env bash
# scripts/iso-e2e.sh — TunaOS live-ISO end-to-end smoke test.
#
# Boots a pre-built ISO in QEMU under OVMF/AAVMF (UEFI), waits for the TunaOS live
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
#       with encryption.type=tpm2-luks-passphrase against an emulated TPM
#       2.0 (swtpm), then reboot the installed disk and confirm the
#       passphrase unlocks it and login is reached. Requires the swtpm
#       package.
#
#       TPM2 auto-unlock is enrolled by a fisherman#48 first-boot oneshot
#       against the INSTALLED system's own PCR 7 (not at install time — an
#       install-time seal measures the live ISO's boot chain instead, and
#       never unseals afterward; tunaOS#679/#680), so it is not proven by
#       the passphrase gate above. Set TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK=1
#       to additionally reboot a third time with no passphrase and confirm
#       the TPM unlocks it unattended — see Environment below.
#
# Options:
#   --timeout SEC         Per-phase timeout (default: 300)
#   --live-marker RE      Readiness regex for the serial log (env: LIVE_MARKER).
#                         Default TUNAOS_LIVE_READY|TBOX_LIVE_READY — ours and
#                         tacklebox's generic marker for non-tunaOS images.
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
#   TBOX_E2E_SSH_PORT     Host TCP port forwarded to the guest's sshd
#                         (default 2222; see SSH_PORT below).
#   TBOX_E2E_VSOCK_CID    AF_VSOCK guest CID for the SSH fallback (default
#                         SSH_PORT+1000). The harness reaches the guest over
#                         TCP as liveuser first; when nothing listens on guest
#                         TCP 22 (stock Fedora ships sshd.service disabled, so
#                         live media only has systemd-ssh-generator's AF_UNIX
#                         and AF_VSOCK listeners) it falls back to root over
#                         vsock, authenticated by a per-run keypair injected
#                         through the SMBIOS credential ssh.authorized_keys.root
#                         (tacklebox#178). See the Guest SSH transport section.
#   TBOX_E2E_IMAGE        Image ref for the generic (no-fisherman) install
#                         path, e.g. "ublue-os/aurora:stable" (bare org/name
#                         gets a ghcr.io/ prefix) or a fully qualified ref.
#                         When the live image ships no fisherman and this is
#                         set, run_install pulls it in the guest and installs
#                         with `bootc install to-disk` (tpm2-luks under
#                         --luks; the reboot gate then proves TPM auto-unlock
#                         instead of passphrase injection).
#   TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK=1
#                         --luks only. After the passphrase gate passes,
#                         reboot the fisherman-installed disk a third time
#                         with the same swtpm and NO passphrase injected,
#                         and require it to reach login unattended (proving
#                         the fisherman#48 first-boot enrollment oneshot
#                         actually sealed a working key against the
#                         installed system's real PCR 7). Default: 0 (off) —
#                         this is real added runtime + a new failure mode,
#                         so it is opt-in rather than folded into every
#                         --luks cell; docs/LUKS-TPM.md calls this "the
#                         per-variant TPM-enrollment test".
#   E2E_WALL_CLOCK_LIMIT  Seconds before the whole harness gives up and
#                         terminates itself with a diagnosis (default 10800,
#                         0 to disable). Relative to when this script starts.
#   E2E_WALL_CLOCK_DEADLINE
#                         Absolute epoch-seconds by which the harness must
#                         have given up, clamping E2E_WALL_CLOCK_LIMIT down
#                         when less time than that remains. Set this from a
#                         CI job's own timeout so the harness fails with
#                         evidence instead of being cancelled without it —
#                         a relative limit cannot do that, because it does
#                         not know how much of the job budget was already
#                         spent before it was called (#1100).
#
# Exit codes:
#   0  success
#   1  generic failure (see serial log)
#   2  readiness marker not seen within --timeout
#   3  kickstart install failed
#   4  installed system did not boot
#   5  SSH check failed
#   6  pixel gate failed — the installed system reached login but nothing
#      provably rendered (blank/absent capture, or zero timelapse frames on
#      a host where capture works). TUNAOS_PIXEL_GATE=0 downgrades to
#      advisory. See scripts/lib/pixel-gate.sh for the decision table.
#   7  desktop contract failed on the installed system — the DM/session
#      assertions run INSIDE the guest did not pass. Distinct from 6 on
#      purpose: 6 says nothing drew, 7 says the guest itself reports no
#      working desktop, and the two catch different holes (a greeter that
#      draws satisfies 6 and still fails 7). TUNAOS_DESKTOP_CONTRACT=0
#      downgrades to advisory.
#   8  TPM auto-unlock verification failed (only reachable with
#      TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK=1) — the third, no-passphrase boot
#      either still showed the cryptsetup passphrase prompt (the first-boot
#      enrollment oneshot did not seal a working key) or never reached
#      login within --timeout. See installed-tpm-autounlock-serial.log.
#   75 the job budget was already exhausted before the harness started
#      (E2E_WALL_CLOCK_DEADLINE in the past) — nothing was tested, and the
#      fix is upstream of here: whatever ran first is too slow, or the
#      caller's timeout is too small.
#   77 missing dependency (qemu, ovmf, etc.) — distinguishable for CI skip

set -euo pipefail

# ── Argument parsing ────────────────────────────────────────────────────────

ISO_PATH=""
KICKSTART=""
APP_CMD=""
MODE="ready" # ready | install | kickstart | ssh | app-launch
TIMEOUT=300
LIVE_MARKER="${LIVE_MARKER:-TUNAOS_LIVE_READY|TBOX_LIVE_READY}"
OUTPUT_DIR="./iso-e2e-out"
MEMORY=4096
CPUS=4
# Host port forwarded to the guest's sshd. Overridable because the harness
# otherwise cannot coexist with anything else on 2222 — on a shared GPU host
# a rootless container already held it and QEMU died with
# "Could not set up host forwarding rule 'tcp::2222-:22'" — and because two
# runs on one host would collide with each other.
SSH_PORT="${TBOX_E2E_SSH_PORT:-2222}"
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
	--contract)
		# --disk only: which in-image contract marker gates the boot.
		# 'desktop' waits for TUNAOS_DESKTOP_CONTRACT_*, 'base' for
		# TUNAOS_BASE_CONTRACT_*. Validated where disk mode reads it.
		DISK_CONTRACT="$2"
		shift 2
		;;
	--live-marker)
		LIVE_MARKER="$2"
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
		# Print the entire leading comment block instead of a fixed line
		# range, which silently truncated help mid-sentence whenever the
		# docs above grew.
		awk 'NR > 1 { if (!/^#/) exit; print }' "$0"
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

# ConnectTimeout bounds the handshake; ServerAlive* bounds an already-open
# connection to a guest that stopped answering. Without the latter, ssh/scp
# block on a dead socket forever — three LUKS runs on 07-31 each burned
# 2h14m-2h42m of a runner inside one scp and had to be cancelled by hand
# (#939).
#
# Defined ONCE, at file scope, because the drift is the actual bug: check_ssh()
# carried ConnectTimeout=10 while the two arrays inside run_smoke_checks() and
# run_install() carried neither guard, so the same file behaved both ways
# depending on which path you were on. Two copies that must agree will stop
# agreeing; #940 fixed the values in both places and left the shape that let
# them diverge.
#
# ServerAliveCountMax=8 (~120s to declare a dead peer) rather than 4 (~60s):
# during a multi-GB transfer into a nested QEMU on a shared runner, sshd can
# plausibly go unresponsive for a minute under I/O pressure without being
# dead, and a false positive here kills a *working* run. Against a hang that
# previously ran for two hours, the extra 60s of detection latency costs
# nothing. Matches the value #940 landed.
E2E_SSH_OPTS=(
	-o StrictHostKeyChecking=no
	-o UserKnownHostsFile=/dev/null
	-o ConnectTimeout=10
	-o ServerAliveInterval=15
	-o ServerAliveCountMax=8
)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/pixel-gate.sh
. "${SCRIPT_DIR}/lib/pixel-gate.sh"
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

# Pick the QEMU binary and machine type for the host architecture. Artifact
# jobs run natively, so an aarch64 host must use the ARM system emulator and
# the ARM `virt` machine rather than the x86_64 emulator and `pc` machine.
HOST_ARCH="$(uname -m)"
QEMU=""
QEMU_MACHINE=""
case "$HOST_ARCH" in
	aarch64 | arm64)
		QEMU_MACHINE="virt"
		QEMU_CANDIDATES=(/usr/bin/qemu-system-aarch64 /usr/local/bin/qemu-system-aarch64)
		;;
	x86_64 | amd64)
		QEMU_MACHINE="pc"
		QEMU_CANDIDATES=(/usr/libexec/qemu-kvm /usr/bin/qemu-kvm /usr/bin/qemu-system-x86_64 /home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64)
		;;
	*)
		echo "ERROR: unsupported host architecture: $HOST_ARCH" >&2
		exit 77
		;;
esac
for candidate in "${QEMU_CANDIDATES[@]}"; do
	if [[ -x "$candidate" ]]; then
		QEMU="$candidate"
		break
	fi
done
if [[ -z "$QEMU" ]]; then
	echo "ERROR: no QEMU system emulator found for $HOST_ARCH" >&2
	exit 77
fi

# GPU/display selection. niri (and the other Smithay compositors — xfwl4,
# cosmic-comp) hard-require EGL_EXT_device_drm, which QEMU's plain virtio-gpu
# does NOT provide (blank screen, niri #322/#2567). If a DRM render node is
# present (an iGPU/dGPU host, e.g. the tailnet laptops) and this QEMU has
# virtio-vga-gl, use virgl + egl-headless so those compositors get real GL and
# actually render. Override with TBOX_E2E_GPU=virgl|plain.
#
# On a GPU-less runner we fall back to -vga virtio. This comment used to say
# that was "fine for cosmic/kde/gnome (software fallbacks)". It is not, and
# the claim cost weeks of misdirected debugging: cosmic and xfce are Smithay
# too, so on hosted runners they don't render blank — they never start at
# all. installer-smoke run 29914643652:
#
#   cosmic: libEGL: failed to create dri2 screen
#   xfce:   greetd: check_children: greeter exited without creating a session
#           greetd.service: Failed with result 'start-limit-hit'
#
# There is no software fallback for any of them. KDE is NOT the exception this
# comment previously claimed: plasmalogin's autologin session and its greeter
# both die instantly on a hosted runner (installer-smoke run 30234237855):
#
#   plasmalogin-helper: Starting Wayland user session ... startplasma-wayland
#   plasmalogin-helper: pam_unix(plasmalogin-autologin:session): session closed
#   plasmalogin: Auth: plasmalogin-helper exited with 5
#   ... then the same for the greeter, in a restart loop
#
# `eglinfo` on that runner lists no EGL_EXT_device_drm at all, so kwin_wayland
# is in the same position as the Smithay compositors.
#
# GNOME is the only desktop still believed verifiable without a render node,
# and that belief is now untested rather than demonstrated — the smoke matrix
# has never run gnome. For everything else use scripts/iso-e2e-gpu.sh on a
# host with a real render node.
#
# WHETHER OR NOT virgl engages, "GDM slow or black" under this GPU-less path
# is expected and is NOT a boot failure (tunaOS#581). The guest's display
# stack falls back to Mesa's llvmpipe software rasteriser, whose first frame
# can trail the serial contract markers by a minute or more on a 2-4 vCPU
# runner — the VM is healthy and simply has not painted yet. The boot gates
# therefore key off the serial markers (the #575 mitigation), and the
# evidence screenshot waits for paint (wait_for_paint / TBOX_E2E_PAINT_TIMEOUT)
# instead of a fixed sleep. Screendump reads the current scanout buffer, so
# while llvmpipe is mid-frame the capture is black; VT-switching to a tty
# other than the compositor's shows black for a different reason — the live
# squash runs getty only on tty1 and the serial console (ttyS0), so tty3 has
# no console to switch to; the Wayland compositor holds tty1. The serial log
# is the source of truth for "is it up", pixels are only for the gallery.
_gpu_mode="${TBOX_E2E_GPU:-auto}"
QEMU_GPU_ARGS=(-vga virtio -display none)
if [[ "$_gpu_mode" != "plain" ]] && { [[ "$_gpu_mode" == "virgl" ]] || [[ -e /dev/dri/renderD128 ]]; } &&
	"$QEMU" -device help 2>/dev/null | grep -q "virtio-vga-gl"; then
	# egl-headless is NOT a display in its own right — it renders GL locally and
	# expects another UI to present the result. Without one, `screendump` fails:
	#
	#   (qemu) screendump /path/shot.ppm
	#   Error: no surface
	#
	# That is silent in practice: iso-e2e.sh, installer-walkthrough.py,
	# run-walkthrough.sh and the weekly screenshot workflows are ALL built on
	# screendump, and their callers `|| true` past a failure — so switching to
	# a GPU host would have produced zero screenshots while still reporting
	# success. The gap never showed up because virgl only engages on a host
	# with a render node, which CI runners do not have.
	#
	# -vnc is what makes capture possible at all, but note it does NOT rescue
	# screendump: under GL scanout the monitor still answers "no surface". It
	# is the VNC *client* path that works, because the server reads the texture
	# back for its clients — see screenshot() below. A unix socket rather than
	# a :N display keeps this off the network and avoids collisions between
	# concurrent runs.
	# The -vnc argument needs OUTPUT_DIR, which is defined further down, so it
	# is appended there rather than here.
	QEMU_GPU_ARGS=(-device virtio-vga-gl -display "egl-headless,rendernode=/dev/dri/renderD128")
	QEMU_NEEDS_VNC_SURFACE=1
	echo "==> GPU: virgl (virtio-vga-gl + egl-headless /dev/dri/renderD128 + vnc surface) — Smithay compositors can render"
else
	echo "==> GPU: -vga virtio headless (no render node/virgl) — niri/xfwl4 will not render here"
fi

# Locate architecture-appropriate UEFI firmware. Path varies across distros
# (Debian/Ubuntu, Fedora, RHEL, Brew). We also need a writable copy of the
# variables file for UEFI to persist its NVRAM during boot.
UEFI_CODE=""
UEFI_VARS_SRC=""
if [[ "$QEMU_MACHINE" == "virt" ]]; then
	UEFI_CODE_CANDIDATES=(
		/usr/share/AAVMF/AAVMF_CODE.fd
		/usr/share/AAVMF/AAVMF_CODE.ms.fd
		/usr/share/qemu-efi-aarch64/QEMU_EFI.fd
	)
	UEFI_VARS_CANDIDATES=(
		/usr/share/AAVMF/AAVMF_VARS.fd
		/usr/share/AAVMF/AAVMF_VARS.ms.fd
		/usr/share/qemu-efi-aarch64/vars-template-pflash.raw
	)
else
	UEFI_CODE_CANDIDATES=(
		/usr/share/OVMF/OVMF_CODE_4M.fd
		/usr/share/OVMF/OVMF_CODE.fd
		/usr/share/edk2/ovmf/OVMF_CODE.fd
		/usr/share/edk2-ovmf/x64/OVMF_CODE.fd
		/usr/share/ovmf/OVMF.fd
		/home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-code.fd
	)
	UEFI_VARS_CANDIDATES=(
		/usr/share/OVMF/OVMF_VARS_4M.fd
		/usr/share/OVMF/OVMF_VARS.fd
		/usr/share/edk2/ovmf/OVMF_VARS.fd
		/usr/share/edk2-ovmf/x64/OVMF_VARS.fd
	)
fi
for f in "${UEFI_CODE_CANDIDATES[@]}"; do
	if [[ -f "$f" ]]; then
		UEFI_CODE="$f"
		break
	fi
done
for f in "${UEFI_VARS_CANDIDATES[@]}"; do
	if [[ -f "$f" ]]; then
		UEFI_VARS_SRC="$f"
		break
	fi
done
if [[ -z "$UEFI_CODE" ]]; then
	echo "ERROR: UEFI firmware not found for $HOST_ARCH — install the architecture's OVMF/AAVMF package" >&2
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
CPU_ARG="max"
if [[ "$ACCEL" == "kvm" ]]; then
	CPU_ARG="host"
elif [[ "$QEMU_MACHINE" == "pc" ]]; then
	# Broaden the TCG CPU to include modern extensions that post-2020
	# shim/GRUB binaries require. The default qemu64 omits SSE4, AES-NI,
	# XSAVE, and AVX, causing #UD crashes when loading EFI bootloaders
	# from newer distros (e.g. AlmaLinux Kitten 10 / yellowfin).
	CPU_ARG="qemu64,+sse4.1,+sse4.2,+aes,+xsave,+xsaveopt,+xsavec,+xsaves,+popcnt,+avx,+avx2"
fi

# Fail early and legibly if the forward port is taken. QEMU's own error —
# "Could not set up host forwarding rule 'tcp::2222-:22'" — arrives after the
# disk image is created and reads like a QEMU fault rather than "something
# else is already listening".
if command -v ss &>/dev/null && ss -tln 2>/dev/null | grep -q ":${SSH_PORT} "; then
	echo "ERROR: port ${SSH_PORT} is already in use; the guest SSH forward cannot bind." >&2
	echo "       Set TBOX_E2E_SSH_PORT to a free port, e.g.:" >&2
	echo "         TBOX_E2E_SSH_PORT=2322 $0 $*" >&2
	exit 77
fi

# ── Per-run scratch files ───────────────────────────────────────────────────

OVMF_VARS="${OUTPUT_DIR}/UEFI_VARS.fd"
MONITOR_SOCK="${OUTPUT_DIR}/monitor.sock"
SERIAL_LOG="${OUTPUT_DIR}/serial.log"
LIVE_SERIAL_LOG="${OUTPUT_DIR}/live-serial.log"
LUKS_EVIDENCE_LOG="${OUTPUT_DIR}/luks-evidence.log"
INSTALL_DISK="${OUTPUT_DIR}/install-disk.qcow2"
QEMU_PIDFILE="${OUTPUT_DIR}/qemu.pid"

# What the run is currently waiting on, as a file rather than a variable: the
# wall-clock watchdog below runs in a background subshell forked before any of
# this happens, so it has a frozen copy of every variable and can only learn
# the current phase by reading it back off disk. Without that, a watchdog
# firing can say "it hung" but not "it hung waiting for X", which is most of
# the value (#1100).
PHASE_FILE="${OUTPUT_DIR}/current-phase.txt"
: >"$PHASE_FILE"

# Announce a phase AND record it for the watchdog. Same output as the plain
# `echo "==> ..."` it replaces, so nothing that greps this log changes.
e2e_phase() {
	printf '%s | %s\n' "$(date -u +%H:%M:%SZ)" "$*" >"$PHASE_FILE"
	echo "==> $*"
}

# A dedicated swap disk for the live guest, attached only to the install boot.
#
# The composefs install path cannot use fisherman's bootcDirect shortcut: bootc
# has to run in a container, so podman first copies the exported OCI layout
# into a scratch store, and podman's anonymous memory during that copy scales
# with the image, not with a fixed buffer. Measured on run 30730744132
# (sailfin:gnome, 8192 MiB guest, no swap):
#
#   Out of memory: Killed process 2978 (podman) total-vm:9250052kB,
#   anon-rss:7147396kB ... Free swap = 0kB / Total swap = 0kB
#
# It was still growing when the kernel killed it, i.e. raising --memory alone
# only moves the cliff: the guest has to have somewhere to push cold pages.
#
# CORRECTION (tunaOS#972). That allocation was not the OCI copy. The live root
# listed /var/lib/superiso-store in /etc/containers/mounts.conf, and podman's
# mounts.conf handling reads the entire source tree into memory and copies it
# into the container's runroot — a tmpfs here — so every install container
# duplicated the payload store twice over. Run 30731534696 (10240 MiB + this
# swap disk) proved it by failing the same way with ENOSPC on /run instead of
# an OOM. customize-live.sh no longer writes that file. The swap disk stays as
# cheap headroom for the real staging copies, but it is no longer load-bearing.
# The live root cannot hold a swapfile (its writable layer is a tmpfs, so a
# swapfile there is memory backed by memory), and the target disk is about to
# be repartitioned, so swap needs a disk of its own. Sparse qcow2: it only
# occupies what the guest actually pages out.
#
# Addressed by serial (/dev/disk/by-id/virtio-e2eswap), never by /dev/vdX: the
# fisherman recipe installs to /dev/vda and this disk must never be confused
# with it.
SWAP_DISK="${OUTPUT_DIR}/swap-disk.qcow2"
SWAP_DISK_SERIAL="e2eswap"
SWAP_DISK_BYID="/dev/disk/by-id/virtio-${SWAP_DISK_SERIAL}"

# A scratch disk for the generic (no-fisherman) install path's container
# storage. The live overlay's upperdir is an 8G tmpfs backed by guest RAM +
# swap, so a stock-image pull (aurora ≈ 9G uncompressed) physically cannot
# land there — the same wall #941 measured from the other direction.
# Attached to every live boot (a sparse qcow2 costs nothing unless written)
# and only formatted/mounted by run_install_generic; addressed by serial for
# the same never-confuse-with-vda reason as the swap disk.
SCRATCH_DISK="${OUTPUT_DIR}/scratch-disk.qcow2"
SCRATCH_DISK_SERIAL="e2escratch"
SCRATCH_DISK_BYID="/dev/disk/by-id/virtio-${SCRATCH_DISK_SERIAL}"

# QEMU writes the guest console into SERIAL_LOG, and several code paths below
# tee ssh output into that same file. `-serial file:PATH` opens the file
# O_WRONLY|O_CREAT|O_TRUNC and writes at QEMU's OWN offset, so the moment a
# tee appends, every later console write lands back in the middle of the file
# and overwrites whatever the tee put there (and vice versa).
#
# That is not theoretical. run 30729902967's serial.log carries a shredded
# `ot ok - network connectivity` line, and the guest console goes silent from
# the first tee onward, which is exactly the window (the bootc install) where
# an OOM report, hung-task splat or panic would have explained why the guest
# stopped answering ssh. The evidence was overwritten, so the failure could
# not be diagnosed from the artifact at all.
#
# append=on opens O_APPEND instead: both writers always land at EOF, so the
# console and the ssh transcript interleave instead of eating each other.
# Nothing relies on QEMU truncating: the log is rm -f'd per run below and
# explicitly truncated before the installed boot.
E2E_SERIAL_ARGS=(
	-chardev "file,id=e2eserial,path=${SERIAL_LOG},append=on"
	-serial chardev:e2eserial
)

# See the egl-headless block above: it renders GL but presents nothing, so
# screendump has no surface and every screenshot in this repo silently fails.
# (VNC alone does not fix screendump under GL scanout — see screenshot().)
# VNC on a unix socket materialises the framebuffer without opening a port.
if [[ "${QEMU_NEEDS_VNC_SURFACE:-0}" == "1" ]]; then
	QEMU_GPU_ARGS+=(-vnc "unix:${OUTPUT_DIR}/vnc.sock")
fi

# ── Guest SSH transport ─────────────────────────────────────────────────────
# Everything that talks to the guest goes through GUEST_SSH/GUEST_SCP, set
# here once (the per-function copies used to drift — see E2E_SSH_OPTS above).
# Two transports exist:
#
#   tcp   (default) sshpass as liveuser through QEMU's hostfwd on
#         127.0.0.1:${SSH_PORT}. Requires the image to ship a TCP sshd and a
#         liveuser with password "live" — true for every tunaOS live ISO.
#   vsock root over AF_VSOCK. Stock Fedora — and therefore the non-tunaOS
#         reference images (aurora, bluefin) — ships sshd.service disabled;
#         on live media only systemd-ssh-generator's AF_UNIX + AF_VSOCK
#         listeners exist, so every hostfwd connection is reset and the tcp
#         probe loops to timeout (tacklebox#178, iso-builder run 31105807882).
#         The generator's vsock listener is purpose-built for exactly this
#         kind of VM access, and systemd's tmpfiles provision.conf (v254+)
#         imports the SMBIOS credential ssh.authorized_keys.root into
#         /root/.ssh/authorized_keys at boot — so a per-run keypair passed on
#         the QEMU command line authenticates root with zero image changes.
#
# check_ssh() probes tcp first and only switches to vsock when tcp fails but
# the vsock listener answers, so tunaOS images keep the exact path they have
# always had. Once chosen, the transport sticks for the rest of the run.
SSH_TRANSPORT="tcp"
GUEST_HOME="/home/liveuser"
GUEST_SCP_DEST="liveuser@127.0.0.1"
GUEST_SSH=()
GUEST_SCP=()
VSOCK_WHY=""

# Guest CIDs 0-2 are reserved (hypervisor/loopback/host). Deriving the CID
# from the (already collision-managed) SSH port keeps two concurrent runs on
# one host from fighting over a CID the same way they would over port 2222.
VSOCK_CID="${TBOX_E2E_VSOCK_CID:-$((SSH_PORT + 1000))}"
VSOCK_SSH_KEY="${OUTPUT_DIR}/vsock-ssh-key"
VSOCK_ARGS=()

use_tcp_transport() {
	SSH_TRANSPORT="tcp"
	GUEST_HOME="/home/liveuser"
	GUEST_SCP_DEST="liveuser@127.0.0.1"
	GUEST_SSH=(sshpass -p live ssh "${E2E_SSH_OPTS[@]}" -p "$SSH_PORT" liveuser@127.0.0.1)
	# scp takes -P (capital) for the port; sharing one array with ssh's -p
	# is how #941's "stat local 2222" bug happened. Keep them separate.
	GUEST_SCP=(sshpass -p live scp "${E2E_SSH_OPTS[@]}" -P "$SSH_PORT")
}

use_vsock_transport() {
	SSH_TRANSPORT="vsock"
	GUEST_HOME="/root"
	# The hostname is never resolved (ProxyCommand carries the connection);
	# it only names the guest in known-hosts noise and scp destinations.
	GUEST_SCP_DEST="root@e2e-vsock"
	local -a common=(
		-i "$VSOCK_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes
		-o "ProxyCommand=socat - VSOCK-CONNECT:${VSOCK_CID}:22"
	)
	GUEST_SSH=(ssh "${common[@]}" "${E2E_SSH_OPTS[@]}" root@e2e-vsock)
	GUEST_SCP=(scp "${common[@]}" "${E2E_SSH_OPTS[@]}")
}
use_tcp_transport

# Host-side requirements for the fallback: a writable /dev/vhost-vsock (the
# module is usually shipped but not loaded — in CI this script runs as root,
# so load it here rather than asking every workflow to), a vsock-capable
# socat for the ProxyCommand, and ssh-keygen for the per-run key. Missing any
# of them just leaves VSOCK_ARGS empty: the QEMU command line is unchanged
# and the harness behaves exactly as before the fallback existed.
setup_vsock() {
	if [[ ! -e /dev/vhost-vsock ]]; then
		modprobe vhost_vsock 2>/dev/null || sudo -n modprobe vhost_vsock 2>/dev/null || true
	fi
	if [[ ! -w /dev/vhost-vsock ]]; then
		echo "==> vsock SSH fallback unavailable (no writable /dev/vhost-vsock) — TCP only"
		return 0
	fi
	if ! command -v socat &>/dev/null || ! socat -V 2>/dev/null | grep -qi vsock; then
		echo "==> vsock SSH fallback unavailable (no vsock-capable socat) — TCP only"
		return 0
	fi
	command -v ssh-keygen &>/dev/null || return 0
	rm -f "$VSOCK_SSH_KEY" "${VSOCK_SSH_KEY}.pub"
	ssh-keygen -q -t ed25519 -N "" -C "tunaos-iso-e2e" -f "$VSOCK_SSH_KEY"
	# base64 without -w0 for macOS compatibility; the credential value must
	# be one SMBIOS string, so strip the wrapping newlines. The base64
	# alphabet contains no commas, so no QEMU option-escaping is needed.
	local pub_b64
	pub_b64=$(base64 <"${VSOCK_SSH_KEY}.pub" | tr -d '\n')
	# The key rides under TWO credential names because they are consumed by
	# different mechanisms and only the second one is known to work on the
	# aurora-shaped images this fallback exists for:
	#
	#   ssh.authorized_keys.root — tmpfiles provision.conf writes it to
	#     /root/.ssh/authorized_keys. On bootc/ostree images /root is a
	#     symlink into /var/roothome, and aurora attempt 7 (iso-builder run
	#     31115116876) proved the file never lands: the vsock handshake
	#     completed and sshd answered "Permission denied (publickey)".
	#     Kept because it is the documented generic mechanism and costs one
	#     SMBIOS string.
	#   ssh.ephemeral-authorized_keys-all — imported by the generated
	#     sshd-vsock/sshd-unix-local instances themselves (verified in
	#     aurora's systemd-ssh-generator: AuthorizedKeysFile
	#     ${CREDENTIALS_DIRECTORY}/ssh.ephemeral-authorized_keys-all),
	#     valid for every user with no home-directory involvement — exactly
	#     the listener this fallback dials.
	VSOCK_ARGS=(
		-device "vhost-vsock-pci,guest-cid=${VSOCK_CID}"
		-smbios "type=11,value=io.systemd.credential.binary:ssh.authorized_keys.root=${pub_b64}"
		-smbios "type=11,value=io.systemd.credential.binary:ssh.ephemeral-authorized_keys-all=${pub_b64}"
	)
	echo "==> vsock SSH fallback armed (guest-cid=${VSOCK_CID})"
}
setup_vsock

record_luks_evidence() {
	[[ "$LUKS" -eq 1 ]] || return 0
	echo "$1" | tee -a "$LUKS_EVIDENCE_LOG"
}

# ── Emulated TPM 2.0 (swtpm) — LUKS mode only ───────────────────────────────
# Every boot that needs the TPM — the generic (--block-setup tpm2-luks)
# path's install-time enrollment, fisherman's first-boot enrollment oneshot
# (tunaOS#680), and any later unlock/verification boot — must see the SAME
# swtpm STATE, so TPM_DIR is created once and reused (start_swtpm keep)
# across boots. The swtpm PROCESS itself does not survive a boot on its own,
# though: it exits when the QEMU it is attached to disconnects, so each
# caller that needs it on a later boot restarts it against the preserved
# state dir rather than assuming it is still running. TPM_ARGS is empty
# unless --luks is set, so non-LUKS modes are byte-for-byte unchanged.
TPM_DIR="${OUTPUT_DIR}/swtpm"
TPM_SOCK="${TPM_DIR}/swtpm-sock"
TPM_PIDFILE="${TPM_DIR}/swtpm.pid"
TPM_ARGS=""

start_swtpm() {
	# "keep": preserve the TPM state dir. swtpm exits when its QEMU
	# disconnects, so the generic path's auto-unlock reboot has to restart
	# it — and the LUKS key bootc sealed at install time only unseals
	# against that same state.
	local keep="${1:-}"
	command -v swtpm &>/dev/null || {
		echo "ERROR: --luks requires swtpm (install the 'swtpm' package)" >&2
		return 77
	}
	[[ "$keep" == "keep" ]] || rm -rf "$TPM_DIR"
	rm -f "$TPM_SOCK" "$TPM_PIDFILE"
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
if [[ -n "$UEFI_VARS_SRC" ]]; then
	cp -f "$UEFI_VARS_SRC" "$OVMF_VARS"
else
	# Some packaging only ships a combined OVMF.fd; create empty vars file
	# as a fallback (UEFI will populate it).
	truncate -s 4M "$OVMF_VARS"
fi
rm -f "$MONITOR_SOCK" "$SERIAL_LOG" "$QEMU_PIDFILE"

# ── Cleanup on exit ─────────────────────────────────────────────────────────

# Clear the unix sockets a previous QEMU left behind, immediately before
# launching the next one. This is bug 1 of #946.
#
# QEMU does not unlink a stale unix socket before binding, and — critically —
# it does not fail either: it logs nothing and boots on with no VNC server.
# So the installed-boot VM silently had no VNC at all, socat got "Connection
# refused", the capture fell back to screendump, and screendump cannot read a
# GL scanout — hence `rendered=absent` on the only host configuration where
# the render path can work at all.
#
# Called from every launcher rather than from cleanup_vm: cleanup runs on the
# way out, and the run that matters is the one that starts next.
reset_qemu_sockets() {
	rm -f "${OUTPUT_DIR}/vnc.sock" "$MONITOR_SOCK"
}

# shellcheck disable=SC2329  # invoked via `trap cleanup_vm EXIT`
cleanup_vm() {
	# Stop the timelapse FIRST, while QEMU is still alive: the recorder reads
	# frames through the monitor socket, and everything below this point is
	# dedicated to killing the process that serves it. Assembly itself needs
	# no VM, but a recorder still looping against a dead socket would spin
	# until the trap finished.
	#
	# Unconditional and non-fatal. record-timelapse.sh returns 0 when there is
	# nothing to assemble, and this runs on the EXIT trap — an error here would
	# overwrite the exit status of the test that actually ran.
	if [[ -n "${TIMELAPSE_DIR:-}" ]]; then
		bash "${SCRIPT_DIR}/record-timelapse.sh" stop "$TIMELAPSE_DIR" || true
	fi
	# `|| true` is load-bearing under `set -e`: once the watchdog has FIRED it
	# has already exited, so this kill fails, and without the guard the
	# non-zero status aborts cleanup_vm right here — skipping the QEMU and
	# swtpm teardown below in precisely the case that needs it most, leaving
	# both orphaned on the runner. Verified by running the pattern both ways.
	if [[ -n "${WATCHDOG_PID:-}" ]]; then
		kill "$WATCHDOG_PID" 2>/dev/null || true
	fi
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
# Without this, SIGTERM kills the shell outright and the EXIT trap never runs,
# so the watchdog below would leave QEMU and swtpm orphaned on the runner.
trap 'exit 143' TERM

# ── Wall-clock backstop ───────────────────────────────────────────────────
# #940 bounded the scp and added keepalives, which fixes the hang we know
# about. This bounds the harness as a WHOLE, which is a different guarantee:
# per-call `timeout` wrappers keep getting missed one at a time, and that is
# precisely how the scp in run_install() went unguarded while both its
# neighbours — the `podman load` after it and `timeout 1800` on fisherman —
# were bounded. Nobody omitted it on purpose.
#
# `--timeout 1200` does not cover this: it is per-phase, consulted only at the
# readiness marker and the graphical-session wait, so the workflow passing it
# bought nothing during the transfer.
#
# The point is the failure MODE, not the specific bug. With this, the next
# missed guard produces a red cell with evidence and a pointer to the line it
# hung on. Without it, three runs held runners for 2h14m-2h42m and left no
# diagnosis at all — the log had to be recovered by cancelling them by hand,
# because GitHub returns BlobNotFound for a running job.
#
# Deliberately generous. 10800 is not arbitrary: it is what this script's own
# per-call guards can legitimately add up to on the slowest path (1800 pull +
# 1800 podman run + 1800 scp + 1800 podman load + 3600 fisherman install), so
# anything shorter as a fixed value could cut off a working-but-slow run.
# Set E2E_WALL_CLOCK_LIMIT=0 to disable.
E2E_WALL_CLOCK_LIMIT="${E2E_WALL_CLOCK_LIMIT:-10800}"

# ...but "generous" is only safe if the job actually has that much time left,
# and the old comment here reasoned that 10800s sits "well under
# timeout-minutes: 240" — comparing the script's budget against the WHOLE
# job's budget while ignoring everything the job does before calling us.
# luks-e2e.yml spends a dev-ISO build first, and that is not small: guppy:xfce
# takes ~133 min there (runs 31232170155 and 31242742608, 133m30s and
# 132m18s), leaving ~105 min of the 240. A 180-minute relative backstop cannot
# fire inside 105 minutes, so on those cells this watchdog was dead code and
# the job-level timeout won instead — which cancels the job and takes the
# `if: always()` Collect/Upload evidence steps with it. That is precisely the
# outcome this backstop exists to prevent (#1100).
#
# So take an ABSOLUTE deadline from the caller and clamp to whichever comes
# first. This can only ever shorten the budget to something the job was never
# going to grant anyway — the job would have been killed at that point
# regardless, just without a diagnosis — so it introduces no risk of failing a
# run that would otherwise have passed.
if [[ -n "${E2E_WALL_CLOCK_DEADLINE:-}" ]]; then
	_remaining=$((E2E_WALL_CLOCK_DEADLINE - $(date +%s)))
	if ((_remaining <= 0)); then
		echo "ERROR: no time left in the job budget before iso-e2e.sh even started" >&2
		echo "       (E2E_WALL_CLOCK_DEADLINE=${E2E_WALL_CLOCK_DEADLINE} is already past)." >&2
		echo "       Everything before this step consumed the job's timeout-minutes." >&2
		exit 75
	fi
	# A deadline arms the watchdog even when the relative limit was disabled:
	# E2E_WALL_CLOCK_LIMIT=0 says "I don't want an arbitrary cap", not "let
	# the job get killed undiagnosed".
	if [[ "$E2E_WALL_CLOCK_LIMIT" -eq 0 ]]; then
		echo "==> Wall-clock backstop armed at ${_remaining}s by the job deadline (relative limit disabled)"
		E2E_WALL_CLOCK_LIMIT="$_remaining"
	elif ((_remaining < E2E_WALL_CLOCK_LIMIT)); then
		echo "==> Wall-clock backstop clamped to ${_remaining}s by the job deadline (was ${E2E_WALL_CLOCK_LIMIT}s)"
		E2E_WALL_CLOCK_LIMIT="$_remaining"
	fi
fi

# What the watchdog prints when it fires. Defined HERE, above the fork, because
# the subshell only has the functions and variables that existed when it was
# forked. "It hung" is not a diagnosis; the phase it hung in and the tail of
# the console it went quiet on are.
dump_hang_diagnosis() {
	local phase="(never recorded)" log
	[[ -s "$PHASE_FILE" ]] && phase="$(cat "$PHASE_FILE")"
	echo "===== iso-e2e.sh hang diagnosis ====================================="
	echo "waiting on : ${phase}"
	echo "mode       : ${MODE}  luks=${LUKS}  variant=${VARIANT:-?}:${FLAVOR:-?}"
	if [[ -f "$QEMU_PIDFILE" ]] && kill -0 "$(cat "$QEMU_PIDFILE" 2>/dev/null)" 2>/dev/null; then
		echo "qemu       : alive (pid $(cat "$QEMU_PIDFILE")) — the guest stopped talking, not QEMU"
	else
		echo "qemu       : not running — the guest died or was never started"
	fi
	for log in "$SERIAL_LOG" "$LIVE_SERIAL_LOG" \
		"${OUTPUT_DIR}/installed-serial.log" \
		"${OUTPUT_DIR}/installed-tpm-autounlock-serial.log"; do
		[[ -s "$log" ]] || continue
		echo "----- last 40 lines of ${log##*/} ($(wc -c <"$log") bytes) -----"
		tail -n 40 "$log" | tr -d '\r'
	done
	echo "====================================================================="
}

WATCHDOG_PID=""
if [[ "$E2E_WALL_CLOCK_LIMIT" -gt 0 ]]; then
	(
		sleep "$E2E_WALL_CLOCK_LIMIT"
		echo "ERROR: iso-e2e.sh exceeded its ${E2E_WALL_CLOCK_LIMIT}s wall-clock limit — terminating" >&2
		# Both destinations on purpose: stderr reaches the job log, and the
		# evidence log reaches the uploaded artifact. The job log is the one
		# that is NOT retrievable while a run is still going (GitHub answers
		# BlobNotFound), which is how the 07-31 hangs left nothing behind.
		dump_hang_diagnosis 2>&1 | tee -a "$LUKS_EVIDENCE_LOG" >&2
		echo "       See tunaOS#939 and tunaOS#1100." >&2
		kill -TERM "$$" 2>/dev/null || true
	) &
	WATCHDOG_PID=$!
fi

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

	# See SWAP_DISK above. Attached to the live/install boot only; the
	# installed system is booted without it and never records it in fstab.
	if [[ ! -f "$SWAP_DISK" ]]; then
		echo "==> Creating 8G swap disk: ${SWAP_DISK}"
		if ! qemu-img create -f qcow2 "$SWAP_DISK" 8G; then
			echo "ERROR: qemu-img create failed for the swap disk" >&2
			return 1
		fi
	fi

	# See SCRATCH_DISK above. Live boot only, like the swap disk.
	if [[ ! -f "$SCRATCH_DISK" ]]; then
		echo "==> Creating 32G scratch disk: ${SCRATCH_DISK}"
		if ! qemu-img create -f qcow2 "$SCRATCH_DISK" 32G; then
			echo "ERROR: qemu-img create failed for the scratch disk" >&2
			return 1
		fi
	fi

	# Kernel cmdline override: append `console=ttyS0` so the live env's
	# tunaos-live-ready.service marker reaches the serial log. We do this
	# via the OVMF boot menu's cmdline editing path, which the ISO's
	# grub.cfg accepts via the standard "e" key — but in unattended mode
	# we instead rely on the ISO's default cmdline already enabling
	# console=ttyS0 (livesys-config does this in upstream).

	e2e_phase "Booting ISO: ${ISO_PATH}"
	echo "==> Accel: ${ACCEL}, CPU: ${CPU_ARG}, MEM: ${MEMORY}M, CPUS: ${CPUS}"

	# shellcheck disable=SC2086  # TPM_ARGS is intentionally word-split (empty unless --luks)
	reset_qemu_sockets
	"$QEMU" \
		-name "tunaos-iso-e2e" \
		-machine "$QEMU_MACHINE" \
		-cpu "$CPU_ARG" \
		-accel "$ACCEL" \
		-m "$MEMORY" \
		-smp "$CPUS" \
		${TPM_ARGS} \
		-drive "if=pflash,format=raw,readonly=on,file=${UEFI_CODE}" \
		-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
		-drive "if=none,id=iso,file=${ISO_PATH},media=cdrom,readonly=on,format=raw" \
		-device virtio-scsi-pci,id=scsi \
		-device scsi-cd,drive=iso \
		-drive "if=none,id=disk,file=${INSTALL_DISK},format=qcow2" \
		-device virtio-blk-pci,drive=disk \
		-drive "if=none,id=swapdisk,file=${SWAP_DISK},format=qcow2" \
		-device "virtio-blk-pci,drive=swapdisk,serial=${SWAP_DISK_SERIAL}" \
		-drive "if=none,id=scratchdisk,file=${SCRATCH_DISK},format=qcow2" \
		-device "virtio-blk-pci,drive=scratchdisk,serial=${SCRATCH_DISK_SERIAL}" \
		-netdev "user,id=net0,hostfwd=tcp::${SSH_PORT}-:22" \
		-device virtio-net-pci,netdev=net0 \
		${VSOCK_ARGS[@]+"${VSOCK_ARGS[@]}"} \
		-monitor "unix:${MONITOR_SOCK},server,nowait" \
		"${E2E_SERIAL_ARGS[@]}" \
		"${QEMU_GPU_ARGS[@]}" \
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

# Take a screenshot. Best-effort, and deliberately two-path.
#
# `screendump` cannot capture a guest that is scanning out through virgl. Once
# a Wayland compositor takes over, the framebuffer lives in a GL texture that
# QEMU's console layer never sees, and the monitor answers:
#
#   (qemu) screendump /path/shot.ppm
#   Error: no surface
#
# Attaching -vnc is necessary but NOT sufficient: with VNC listening,
# screendump still reports "no surface" under GL scanout. Verified on hardware
# 2026-07-26 — it succeeds at the pre-GL text console and fails the moment
# cosmic-comp starts, which is precisely the window we care about.
#
# The VNC *client* path does work, because the VNC server reads the texture
# back for its clients. Capturing through it produced the first image ever
# taken of the cosmic live session with the installer on screen.
#
# So: prefer VNC capture whenever the socket exists, and keep screendump as
# the fallback for the plain -vga virtio path, where it is perfectly good.
screenshot() {
	local label="$1"
	local out="${OUTPUT_DIR}/${label}.ppm"
	local png="${OUTPUT_DIR}/${label}.png"
	local vnc_sock="${OUTPUT_DIR}/vnc.sock"

	local cap_log="${OUTPUT_DIR}/vnc-capture-${label}.log"

	if [[ -S "$vnc_sock" ]] && command -v vncdo &>/dev/null && command -v socat &>/dev/null; then
		# vncdo speaks TCP, so bridge the unix socket for the moment of capture.
		#
		# A FRESH PORT PER CAPTURE, and no `fork` — this is bug 2 of #946.
		# The old bridge was `TCP-LISTEN:...,fork`, which forks a child per
		# connection; `kill $bridge` reaps only the listener, so children
		# bridging to a socket whose QEMU has since been killed survive and
		# keep the port warm. The next capture then connects to one of those
		# corpses and vncdo reads ECONNRESET — which is exactly the reported
		# signature: the live capture (first use of the port) succeeds, the
		# installed capture (always second) fails with "Connection reset by
		# peer". One capture is one connection, so `fork` bought nothing.
		VNC_BRIDGE_PORT=$((${VNC_BRIDGE_PORT:-${TBOX_E2E_VNC_PORT:-5999}} + 1))
		local port="$VNC_BRIDGE_PORT"
		# bind=127.0.0.1: vncdo connects to loopback, so there is no reason to
		# expose the guest console on every host interface, however briefly —
		# these runs happen on bare-metal hosts on a real LAN.
		socat "TCP-LISTEN:${port},bind=127.0.0.1,reuseaddr" "UNIX-CONNECT:${vnc_sock}" >>"$cap_log" 2>&1 &
		local bridge=$!
		# Wait for the listener instead of sleeping at it: on a loaded host
		# 1s was sometimes short, and the failure was indistinguishable from
		# a real capture failure.
		#
		# Liveness of *this* socat is checked first: a listening port alone
		# proves nothing, since a leftover bridge or an unrelated service can
		# hold it while our socat failed to bind and exited. And the port match
		# is anchored on whitespace/end-of-line — `\b` is not a word boundary
		# in grep's default BRE, so ":5999\b" never matched `ss` output as
		# intended (and a bare ":5999" would also match ":59990").
		local ready=0
		for _ in $(seq 1 20); do
			if ! kill -0 "$bridge" 2>/dev/null; then
				echo "==> VNC bridge exited before listening on ${port}" >>"$cap_log"
				break
			fi
			if command -v ss &>/dev/null; then
				ss -ltn 2>/dev/null | grep -Eq "127\.0\.0\.1:${port}([[:space:]]|$)" && {
					ready=1
					break
				}
			else
				sleep 1
				ready=1
				break
			fi
			sleep 0.25
		done
		[[ "$ready" == 1 ]] || echo "==> VNC bridge never listened on ${port}" >>"$cap_log"
		# Errors go to a per-label log, not /dev/null. #946 bug 2 sat
		# undiagnosed because this line discarded both vncdo's and socat's
		# output, so a failed capture said only "rendered=absent".
		vncdo -s "127.0.0.1::${port}" capture "$png" >>"$cap_log" 2>&1 || true
		kill "$bridge" 2>/dev/null || true
		wait "$bridge" 2>/dev/null || true
		if [[ -s "$png" ]]; then
			echo "==> Screenshot saved: ${png} (vnc)"
			return 0
		fi
		echo "==> VNC capture failed; falling back to screendump (see ${cap_log})" >&2
	fi

	if [[ -S "$MONITOR_SOCK" ]] && command -v socat &>/dev/null; then
		echo "screendump ${out}" | socat - "UNIX-CONNECT:${MONITOR_SOCK}" >/dev/null 2>&1 || true
		if [[ -f "$out" ]]; then
			echo "==> Screenshot saved: ${out}"
		else
			# Say so rather than leaving a silently absent artifact: on the
			# virgl path this is expected, and vncdo is the missing piece.
			echo "==> No screenshot captured (screendump found no surface; install vncdotool for the virgl path)" >&2
		fi
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

# Did the serial log say, in so many words, that the boot failed?
#
# The screenshot fallback below exists because bootc base kernels ship
# CONFIG_SERIAL_8250=m and a healthy live session often cannot get
# the readiness marker onto the serial console. What it cannot distinguish is a
# healthy session from a dracut emergency shell: that renders text too, so
# the framebuffer is "sane" and the run passes.
#
# That is not hypothetical. marlin:kde-cachyos sat in `Dracut Emergency
# Shell` after `/run/tacklebox-live-done does not exist` / `Could not boot`,
# and this script still exited 0. A gate that green-lights an ISO in an
# emergency shell is worse than no gate, especially as the input to a LUKS
# matrix where every cell would inherit the same false pass.
#
# So: absence of the marker stays recoverable, but *evidence of failure* does
# not. These signatures are unambiguous — no healthy boot prints them.
boot_failed_on_serial() {
	[[ -f "$SERIAL_LOG" ]] || return 1
	local sig
	for sig in \
		"Entering emergency mode" \
		"Dracut Emergency Shell" \
		"Warning: Could not boot" \
		"Kernel panic" \
		"You are in emergency mode"; do
		if grep -qF "$sig" "$SERIAL_LOG" 2>/dev/null; then
			echo "ERROR: serial log shows a failed boot: ${sig}" >&2
			echo "       refusing to pass on the screenshot fallback." >&2
			return 0
		fi
	done
	return 1
}

# Sanity-check a captured screenshot: it must exist and show actual content
# (not a black/blank framebuffer). Used as the readiness fallback when the
# serial marker never arrives — the bootc base kernels ship
# CONFIG_SERIAL_8250=m, so the readiness marker often cannot reach the serial
# console even though the live session is up (see research.md).
# Returns 0 if the screenshot looks like a rendered screen, 1 otherwise.
screenshot_sane() {
	local label="$1"
	# screenshot() writes .png on the VNC path and .ppm on the screendump
	# path, and this only ever looked for .ppm — so on the virgl path, where
	# VNC is the ONLY thing that captures anything at all, a perfectly good
	# screenshot read as "no screenshot ... cannot verify". Take whichever
	# landed; ImageMagick measures both the same way.
	local cap="${OUTPUT_DIR}/${label}.png"
	[[ -s "$cap" ]] || cap="${OUTPUT_DIR}/${label}.ppm"
	if [[ ! -s "$cap" ]]; then
		echo "==> No screenshot at ${OUTPUT_DIR}/${label}.{png,ppm} — cannot verify via fallback" >&2
		return 1
	fi
	if ! command -v convert &>/dev/null; then
		# Without ImageMagick we can only check the file is non-trivial. The
		# 100kB floor assumes an uncompressed PPM; PNG of a near-blank screen
		# compresses far below it, so this heuristic cannot judge a PNG at all
		# and must not answer for one.
		if [[ "$cap" == *.png ]]; then
			echo "==> ImageMagick absent; cannot judge PNG ${cap} for blankness" >&2
			return 1
		fi
		local size
		size=$(stat -c%s "$cap" 2>/dev/null || echo 0)
		[[ "$size" -gt 100000 ]] && return 0
		return 1
	fi
	# standard_deviation ~0 means a uniform (blank/black) screen. A rendered
	# DM/desktop always has structure. fx output is 0..1.
	local stddev
	stddev=$(convert "$cap" -colorspace Gray -format "%[fx:standard_deviation]" info: 2>/dev/null || echo 0)
	# Published so callers can record the measurement itself, not just the
	# verdict: "blank" and "stddev=0.0007" answer different questions when the
	# result is being weighed as evidence rather than used as a gate.
	SCREENSHOT_STDDEV="$stddev"
	echo "==> Screenshot ${label} stddev=${stddev}"
	if awk -v s="$stddev" 'BEGIN{exit !(s > 0.02)}'; then
		return 0
	fi
	echo "==> Screenshot ${label} looks blank (stddev=${stddev} <= 0.02)" >&2
	return 1
}

# Give the display manager/desktop time to actually PAINT before the evidence
# screenshot. Under QEMU's plain virtio-vga there is no render node, so the
# guest composites with Mesa's llvmpipe software rasteriser; its first frame
# can trail the serial contract marker by a minute or more on a 2-4 vCPU
# runner (tunaOS#581). A fixed sleep before the screenshot therefore produced
# a black "10-ready" in the evidence gallery for an otherwise-healthy gate,
# and the screenshot-sanity fallback could not tell "slow" from "failed".
#
# Poll the framebuffer instead: screenshot, measure (screenshot_sane), retry
# until the image has structure or the cap is reached. The LAST screenshot is
# always left on disk as evidence. This is evidence, not a gate — pass/fail
# stays with the serial marker (the #575 mitigation) — so a machine that
# genuinely cannot paint extends the wait, it does not fail the run. The
# per-attempt stddev is logged so a blank result stays diagnosable.
wait_for_paint() {
	local label="$1"
	local cap="${TBOX_E2E_PAINT_TIMEOUT:-120}"
	local deadline=$(($(date +%s) + cap))
	local attempt=0
	while (($(date +%s) < deadline)); do
		attempt=$((attempt + 1))
		screenshot "$label"
		if screenshot_sane "$label"; then
			echo "==> ${label} painted on attempt ${attempt} (stddev=${SCREENSHOT_STDDEV:-unmeasured})"
			return 0
		fi
		sleep 15
	done
	# One final capture after the cap so the freshest frame is the evidence.
	screenshot "$label"
	if screenshot_sane "$label"; then
		return 0
	fi
	# :-unmeasured, not a bare expansion: screenshot_sane's early returns (no
	# ImageMagick, no capture) never set SCREENSHOT_STDDEV, and under set -u a
	# bare reference here killed the base Gate's TIMEOUT path before it could
	# print any diagnostics (sailfin run 32068513822, line-1323 crash).
	echo "==> ${label} still blank after ${cap}s (stddev=${SCREENSHOT_STDDEV:-unmeasured}) — the serial marker, not pixels, is the gate" >&2
	return 1
}

# Wait for the live env to print its readiness marker.
wait_for_ready() {
	local deadline=$(($(date +%s) + TIMEOUT))
	local last_size=0
	e2e_phase "Waiting up to ${TIMEOUT}s for readiness marker (${LIVE_MARKER})..."
	while (($(date +%s) < deadline)); do
		if [[ -f "$SERIAL_LOG" ]] && grep -qE -- "$LIVE_MARKER" "$SERIAL_LOG" 2>/dev/null; then
			echo "==> Readiness marker found"
			return 0
		fi
		# Fallback: if SSH is available (dev ISOs), check whether the guest
		# is at least alive and whether tunaos-live-ready.service exists.
		# Use same timeout/pattern as check_ssh but don't block the loop.
		if command -v sshpass &>/dev/null; then
			local ssh_opts="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3"
			if sshpass -p live ssh $ssh_opts liveuser@127.0.0.1 -p "$SSH_PORT" true 2>/dev/null; then
				echo "    [ssh: guest is alive — checking why marker hasn't fired]"
				sshpass -p live ssh $ssh_opts liveuser@127.0.0.1 -p "$SSH_PORT" \
					"systemctl status tunaos-live-ready.service 2>&1 || true; echo '---'; systemctl is-active graphical.target 2>&1 || true" \
					>>"$SERIAL_LOG" 2>/dev/null || true
				# Also try grepping serial log for an install-checks result as
				# a backup readiness signal — it means the system is well past
				# boot and the marker just didn't fire.
				if [[ -f "$SERIAL_LOG" ]] && grep -q "TUNAOS_INSTALL_CHECKS_RESULT" "$SERIAL_LOG" 2>/dev/null; then
					echo "==> Readiness assumed from TUNAOS_INSTALL_CHECKS_RESULT (marker service missing/failed)"
					return 0
				fi
			fi
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
	# Last-resort diagnostic: try SSH to see if guest is alive but marker-less.
	if command -v sshpass &>/dev/null; then
		echo "--- SSH diagnostic (last resort) ---" >&2
		local ssh_opts="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5"
		sshpass -p live ssh $ssh_opts liveuser@127.0.0.1 -p "$SSH_PORT" \
			"echo 'guest uptime:'; uptime; echo '--- systemd state:'; systemctl list-units --state=failed 2>&1 || true; echo '--- tunaos-live-ready:'; systemctl status tunaos-live-ready.service 2>&1 || true; echo '--- graphical.target:'; systemctl status graphical.target 2>&1 || true" \
			2>&1 >&2 || echo "SSH unreachable" >&2
	fi
	return 2
}

# Probe the vsock listener as root with the SMBIOS-provisioned key. On
# success the transport is switched (and sticks) for everything downstream.
check_ssh_vsock() {
	local err
	err=$(mktemp)
	if ssh -i "$VSOCK_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
		-o "ProxyCommand=socat - VSOCK-CONNECT:${VSOCK_CID}:22" \
		"${E2E_SSH_OPTS[@]}" root@e2e-vsock true 2>"$err"; then
		rm -f "$err"
		if [[ "$SSH_TRANSPORT" != "vsock" ]]; then
			echo "==> no TCP sshd on guest; switching to root over AF_VSOCK (systemd-ssh-generator image — tacklebox#178)"
			use_vsock_transport
		fi
		echo "==> SSH OK (vsock cid=${VSOCK_CID})"
		return 0
	fi
	VSOCK_WHY=$(tr -d '\r' <"$err" | grep -v '^Warning: Permanently added' | tr '\n' ' ' | sed 's/  */ /g') || true
	rm -f "$err"
	return 5
}

# Verify SSH connectivity and pick the transport. The tcp path needs an ISO
# built with ENABLE_SSHD=1 (tunaOS live media); generic images without a TCP
# sshd fall back to vsock — see the Guest SSH transport section.
check_ssh() {
	if [[ "$SSH_TRANSPORT" == "vsock" ]]; then
		check_ssh_vsock
		return $?
	fi
	if ! command -v sshpass &>/dev/null; then
		echo "ERROR: sshpass required for --ssh-only; install it" >&2
		return 77
	fi
	local err
	err=$(mktemp)
	if sshpass -p live ssh "${E2E_SSH_OPTS[@]}" liveuser@127.0.0.1 -p "$SSH_PORT" true 2>"$err"; then
		rm -f "$err"
		echo "==> SSH OK"
		return 0
	fi
	# tcp failed. Before reporting, try the vsock fallback: a guest whose
	# only listeners are systemd-ssh-generator's resets every hostfwd
	# connection, and without this the loop above just replays that failure
	# to timeout. Success here flips the transport for the whole run.
	if [[ ${#VSOCK_ARGS[@]} -gt 0 ]] && check_ssh_vsock; then
		rm -f "$err"
		return 0
	fi
	# Say WHY. This used to be `2>/dev/null` with a bare "SSH check failed",
	# repeated up to 30 times — 30 identical lines carrying no more
	# information than one, and none of it the reason.
	#
	# The distinction the discarded stderr carries is the whole diagnosis:
	#   Connection refused   -> nothing listening: port-forward or sshd down
	#   Connection reset     -> sshd is there and rejected the connection
	#   Permission denied    -> reached sshd, auth failed (user/password)
	#   Operation timed out  -> the guest is wedged, not the daemon
	#
	# Measured need: grouper LUKS cells fail here while the guest serial shows
	# "Started ssh.service - OpenBSD Secure Shell server" and the host keys
	# generated (run 30692913767). The daemon is UP and we still cannot say
	# what the client saw, so the same wall has now been hit three times and
	# three separate hypotheses were proposed against zero client-side
	# evidence.
	#
	# The filter can legitimately match nothing (empty stderr, or nothing but
	# the known-hosts warning), and under `pipefail` that grep exits 1. Keep
	# the status off the caller's path with `|| true`, and never emit the bare
	# "SSH check failed:" this whole change exists to eliminate.
	local why=""
	why=$(tr -d '\r' <"$err" | grep -v '^Warning: Permanently added' | tr '\n' ' ' | sed 's/  */ /g') || true
	[[ -n "${why// /}" ]] || why="(no ssh stderr beyond the known-hosts warning)"
	# Both transports were tried; report both reasons or the diagnosis is
	# half-blind (the tcp reset is expected on generic images — the vsock
	# line is the one that says what actually went wrong there).
	if [[ ${#VSOCK_ARGS[@]} -gt 0 && -n "${VSOCK_WHY// /}" ]]; then
		why="tcp: ${why} | vsock: ${VSOCK_WHY}"
	fi
	echo "ERROR: SSH check failed: $why" >&2
	rm -f "$err"
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
	# Transport-aware guest access (keepalive rationale on E2E_SSH_OPTS;
	# transport selection in the Guest SSH transport section).
	local ssh_cmd=("${GUEST_SSH[@]}")
	local scp_cmd=("${GUEST_SCP[@]}")

	"${scp_cmd[@]}" "${script_dir}/lib/e2e-assert.sh" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-assert.sh"
	"${scp_cmd[@]}" "${script_dir}/e2e-smoke-checks.sh" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-smoke-checks.sh"

	local smoke_output smoke_rc=0
	smoke_output=$("${ssh_cmd[@]}" "TEST_LIB_DIR=${GUEST_HOME} bash ${GUEST_HOME}/e2e-smoke-checks.sh" 2>&1) || smoke_rc=$?
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

# Upload and run the TAP-style installer GUI verification checks (tunaOS#678).
# Runs the per-flavor compositor + installer-frontend + readiness-stamp
# assertions inside the live guest, same TAP format as the smoke checks.
# Non-fatal by default; set E2E_INSTALLER_GUI_STRICT=1 to make any failed
# assertion a hard failure.
run_installer_gui_checks() {
	local script_dir
	script_dir="$(dirname "${BASH_SOURCE[0]}")"
	local ssh_cmd=("${GUEST_SSH[@]}")
	local scp_cmd=("${GUEST_SCP[@]}")

	"${scp_cmd[@]}" "${script_dir}/lib/e2e-assert.sh" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-assert.sh"
	"${scp_cmd[@]}" "${script_dir}/e2e-installer-gui-checks.sh" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-installer-gui-checks.sh"

	local gui_output gui_rc=0
	gui_output=$("${ssh_cmd[@]}" "FLAVOR=${FLAVOR:-gnome} TEST_LIB_DIR=${GUEST_HOME} bash ${GUEST_HOME}/e2e-installer-gui-checks.sh" 2>&1) || gui_rc=$?
	echo "$gui_output" | tee -a "${SERIAL_LOG}"
	if [[ "$gui_rc" -ne 0 ]]; then
		echo "::warning::installer GUI checks reported ${gui_rc} failure(s) for ${FLAVOR:-gnome}"
		if [[ "${E2E_INSTALLER_GUI_STRICT:-0}" -eq 1 ]]; then
			echo "ERROR: E2E_INSTALLER_GUI_STRICT=1 and installer GUI checks failed" >&2
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

# ── Guest heartbeat, on the console rather than over ssh ─────────────────
# The install is the one phase where the guest can stop answering while
# QEMU stays up, and `Timeout, server 127.0.0.1 not responding.` on its
# own does not say why: a wedged guest and a live guest whose sshd
# stalled under I/O look identical from the host. Everything else we log
# comes back over the same ssh channel that just died, so it stops
# exactly when the interesting part starts.
#
# This writes to /dev/console (i.e. the serial log) from a process
# setsid'd out of the ssh session, so it keeps reporting after that
# channel is gone. The last line before the silence is the diagnosis:
# memavail collapsing means the guest is out of RAM (raise --memory),
# memavail AND swapfree both collapsing means it is genuinely out of
# memory rather than merely short of it (run 30730744132 killed podman
# that way), target_free collapsing means the disk is, and one that keeps
# ticking through the timeout means the guest was alive all along and
# only sshd stalled.
start_guest_heartbeat() {
	local HB_LOCAL="${OUTPUT_DIR}/e2e-heartbeat.sh"
	cat >"$HB_LOCAL" <<-'HBEOF'
		#!/bin/sh
		while :; do
			printf 'TUNAOS_E2E_HEARTBEAT memavail_kb=%s swapfree_kb=%s dirty_kb=%s writeback_kb=%s target_free_kb=%s load=%s\n' \
				"$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)" \
				"$(awk '/^SwapFree:/{print $2}' /proc/meminfo)" \
				"$(awk '/^Dirty:/{print $2}' /proc/meminfo)" \
				"$(awk '/^Writeback:/{print $2}' /proc/meminfo)" \
				"$(df -Pk /mnt/fisherman-target 2>/dev/null | awk 'NR==2{print $4}')" \
				"$(cut -d' ' -f1-3 /proc/loadavg)" >/dev/console 2>/dev/null
			sleep 15
		done
	HBEOF
	if "${GUEST_SCP[@]}" "$HB_LOCAL" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-heartbeat.sh"; then
		"${GUEST_SSH[@]}" "sudo install -m0755 ${GUEST_HOME}/e2e-heartbeat.sh /usr/local/bin/tunaos-e2e-heartbeat && \
			sudo setsid --fork /usr/local/bin/tunaos-e2e-heartbeat </dev/null >/dev/null 2>&1" ||
			echo "WARN: guest heartbeat did not start (continuing)"
	else
		echo "WARN: guest heartbeat could not be uploaded (continuing)"
	fi
}

# E2E-only kargs on the installed system's BLS entries (the live env can
# still mount the unencrypted ESP/boot). console=ttyS0 puts kernel output on
# the serial the gate reads; plymouth.enable=0 makes the initramfs
# cryptsetup PASSWORD PROMPT appear as serial text instead of a graphical
# plymouth prompt — without it luks-first-boot.py never sees the prompt
# (run 29670982740). Also dumps the ESP: whether the install produced a
# *bootable* disk is only knowable from the ESP, and the ESP is gone the
# moment this VM powers off. sailfin (composefs + systemd-boot) gets no
# NVRAM entry — bootctl refuses to touch efivars from inside the install
# container — so the firmware can only find it via the removable fallback
# \EFI\BOOT\BOOTX64.EFI (or BOOTAA64.EFI on ARM); when that file is missing
# the disk is unbootable
# no matter what the boot order says, and from the serial log alone the
# failure looks identical to a boot-order bug.
append_installed_serial_kargs() {
	echo "==> Appending console=ttyS0 + plymouth.enable=0 to installed BLS entries..."
	"${GUEST_SSH[@]}" 'sudo bash -s' <<-'BLSEOF' 2>&1 | tee -a "$SERIAL_LOG" || echo "WARN: BLS karg append failed (continuing)"
		for p in /dev/vda1 /dev/vda2 /dev/vda3; do
			[ -b "$p" ] || continue
			mkdir -p /mnt/tbx-bls
			mount "$p" /mnt/tbx-bls 2>/dev/null || continue
			found=0
			for f in /mnt/tbx-bls/loader/entries/*.conf /mnt/tbx-bls/boot/loader/entries/*.conf; do
				[ -f "$f" ] || continue
				grep -q "console=ttyS0" "$f" || sed -i "s/^options \(.*\)$/options \1 console=ttyS0,115200n8 rd.plymouth=0 plymouth.enable=0/" "$f"
				echo "karg appended: $f"
				found=1
			done
			if [ "$found" = 1 ]; then
				echo "--- ESP contents ($p) ---"
				find /mnt/tbx-bls -maxdepth 3 2>/dev/null | sort || ls -lR /mnt/tbx-bls || true
				fallback_efi="BOOTX64.EFI"
				[[ "$(uname -m)" == "aarch64" ]] && fallback_efi="BOOTAA64.EFI"
				if [ -f "/mnt/tbx-bls/EFI/BOOT/${fallback_efi}" ]; then
					echo "esp: removable fallback present (EFI/BOOT/${fallback_efi})"
				else
					echo "WARN: esp has NO EFI/BOOT/${fallback_efi}; firmware has no fallback to boot"
				fi
			fi
			umount /mnt/tbx-bls
			[ "$found" = 1 ] && break
		done
	BLSEOF
}

# Wait up to $2 seconds for pid $1 to leave the process table. 0 = it is gone.
wait_pid_gone() {
	local pid="$1" secs="$2" i
	for ((i = 0; i < secs; i++)); do
		kill -0 "$pid" 2>/dev/null || return 0
		sleep 1
	done
	! kill -0 "$pid" 2>/dev/null
}

# Shut the guest down and do not return while its QEMU is still alive.
#
# Both callers launch the installed-disk boot immediately afterwards, reusing
# $QEMU_PIDFILE — and QEMU holds an exclusive lock on that file for its entire
# life. So a guest that overstays its poweroff does not merely delay the next
# boot, it makes it impossible:
#
#   qemu-system-x86_64: cannot create PID file: Cannot lock pid file:
#   Resource temporarily unavailable
#
# which under `set -e` ends the cell right there, minutes after the install it
# was testing had already reported "Installation complete!" (run 31140233496,
# albacore:cosmic). The generic path has a second stake in this: swtpm only
# exits when its QEMU disconnects, and the TPM gate below restarts it.
#
# A guest can overstay for reasons that have nothing to do with the install.
# In that run fisherman had just logged `cryptsetup luksClose: Device
# fisherman-root is still in use`, and a busy dm device is exactly what
# systemd-shutdown spends its shutdown retrying — on top of systemd's own 90s
# DefaultTimeoutStopSec, which the previous 70s window could not outlast.
# Hence: wait long enough for a slow-but-healthy shutdown, then stop asking.
POWEROFF_WAIT_SECS="${TUNAOS_E2E_POWEROFF_WAIT:-180}"

poweroff_and_wait_vm() {
	if ! "${GUEST_SSH[@]}" "sudo systemctl poweroff" 2>/dev/null; then
		# Not fatal: the guest may be going down already (sshd dies mid-command
		# often enough), and ACPI below is a second way in. But it changes what
		# a long wait MEANS, so it must not be silent.
		echo "==> note: 'systemctl poweroff' over ssh did not return cleanly" >&2
	fi
	sleep 10
	[[ -f "$QEMU_PIDFILE" ]] || return 0
	local pid
	pid=$(cat "$QEMU_PIDFILE" 2>/dev/null || true)
	[[ -n "$pid" ]] || return 0
	kill -0 "$pid" 2>/dev/null || return 0

	e2e_phase "Waiting for VM to shut down..."
	wait_pid_gone "$pid" "$POWEROFF_WAIT_SECS" && return 0

	# The install is finished by here — fisherman/bootc have unmounted, frozen
	# and flushed the target filesystem — so ending the guest ourselves costs
	# nothing the following boot needs. The ladder still gives it two chances
	# to end itself first, and only escalates when it will not.
	echo "==> VM did not power off within ${POWEROFF_WAIT_SECS}s; forcing it down" >&2
	if [[ -S "$MONITOR_SOCK" ]] && command -v socat &>/dev/null; then
		echo "system_powerdown" | socat - "UNIX-CONNECT:${MONITOR_SOCK}" 2>/dev/null || true
		wait_pid_gone "$pid" 20 && return 0
	fi
	kill -TERM "$pid" 2>/dev/null || true
	if ! wait_pid_gone "$pid" 10; then
		kill -KILL "$pid" 2>/dev/null || true
		wait_pid_gone "$pid" 5 || true
	fi
	if kill -0 "$pid" 2>/dev/null; then
		echo "ERROR: QEMU pid ${pid} survived SIGKILL; the installed-disk boot cannot" >&2
		echo "       take the ${QEMU_PIDFILE} lock while it holds it." >&2
		return 6
	fi
	# QEMU unlinks its own pidfile when it exits normally and did not get the
	# chance here. Leaving a dead pid behind would have cleanup_vm signalling
	# whatever recycles the number, and would hide that the next launch is
	# starting from a corpse.
	rm -f "$QEMU_PIDFILE"
}

# Prefix a bare "org/name:tag" image path with the default registry; a ref
# whose first path component contains a dot already names its registry host
# and passes through untouched.
qualify_imgref() {
	local ref="$1"
	if [[ "${ref%%/*}" == *"."* ]]; then
		echo "$ref"
	else
		echo "ghcr.io/${ref}"
	fi
}

# Does the embedded offline store's image index record this exact ref?
#
# Takes the index as text rather than a path because it is read out of the guest
# once, over SSH, and answered on the HOST. The guest side of that is `cat`;
# everything that needs a parser runs here, where jq is a declared dependency.
# The previous form asked the guest for `jq`, and a guest that ships neither jq
# nor podman — guppy, whose Gentoo base emerges skopeo for bootc's
# containers-image-proxy and neither of those two — could not answer either
# probe, so a store holding the image read as empty.
#
# `names`, never `names-history`: containers-storage resolves a ref only while
# it is a current name, and a ref that appears solely in the history was
# retagged away. Answering yes for one would send bootc after an image it
# cannot resolve, which is the same dead end by a different road.
store_records_image() {
	local images_json="$1" ref="$2"
	[[ -n "$images_json" && -n "$ref" ]] || return 1
	if command -v jq >/dev/null 2>&1; then
		jq -e --arg ref "$ref" \
			'.[]? | select(.names != null) | select(.names | index($ref))' \
			>/dev/null 2>&1 <<<"$images_json"
		return
	fi
	# No jq on this host either (a bare local run). Match the `names` arrays
	# textually — `"names":` cannot match `"names-history":`, whose next
	# character is `-` — so a missing jq degrades the probe instead of
	# silently turning it off.
	grep -o '"names":\[[^]]*\]' <<<"$images_json" | grep -Fq "\"${ref}\""
}

# Generic install path for live media built from images that ship no
# fisherman — the reference cells (aurora, bluefin) and any stock bootc
# image (tacklebox#178's ladder). Everything tunaOS-specific is skipped: no
# offline store, no recipe, no first-boot passphrase enrollment. Instead:
#
#   - the image named by TBOX_E2E_IMAGE is pulled from its registry into
#     container storage staged on the scratch disk (the live overlay's
#     upperdir is an 8G tmpfs — a multi-GB store physically cannot land
#     there, #941's lesson from the other direction),
#   - bootc install to-disk --wipe runs from the pulled container — the
#     designed non-live install path — with --block-setup tpm2-luks under
#     --luks, and the serial/plymouth kargs baked via --karg,
#   - the LUKS evidence checks reuse scripts/e2e-luks-checks.sh: unlike
#     fisherman's post-install enrollment model, bootc's tpm2-luks enrolls
#     a systemd-tpm2 token at install time, so both TAP checks apply,
#   - the reboot gate boots the installed disk WITH the same swtpm state
#     and expects the TPM to auto-unlock the root. There is no known
#     passphrase to inject (bootc generates and seals its own), so
#     reaching a login prompt on serial IS the unlock proof: a missing or
#     wrong TPM hangs the boot in the initramfs at the cryptsetup prompt.
run_install_generic() {
	local imgref
	imgref="$(qualify_imgref "$TBOX_E2E_IMAGE")"
	echo "==> Generic bootc install path (no fisherman): ${imgref}"
	record_luks_evidence "TUNAOS_LUKS_E2E_GENERIC_PATH image=${imgref}"

	local ssh_cmd=("${GUEST_SSH[@]}")
	local scp_cmd=("${GUEST_SCP[@]}")
	local script_dir
	script_dir="$(dirname "${BASH_SOURCE[0]}")"

	# Same SLIRP PMTU blackhole as the fisherman path (bug #20 there): clamp
	# the guest MTU before the registry pull, or a large layer hangs forever.
	# shellcheck disable=SC2016  # $(...) must expand on the guest
	"${ssh_cmd[@]}" 'for i in $(ls /sys/class/net | grep -v ^lo$); do sudo ip link set "$i" mtu 1400; done; ip -o link show' || true

	echo "==> Running live-image smoke checks..."
	run_smoke_checks || return 3

	echo "==> Staging container storage on ${SCRATCH_DISK_BYID}..."
	"${ssh_cmd[@]}" "sudo sh -c 'test -b ${SCRATCH_DISK_BYID} && mkfs.ext4 -q -L tbxscratch ${SCRATCH_DISK_BYID} && mkdir -p /var/lib/containers && mount ${SCRATCH_DISK_BYID} /var/lib/containers && df -h /var/lib/containers'" || {
		echo "ERROR: could not stage container storage on the scratch disk" >&2
		return 3
	}

	# Swap too — podman's staging allocates anonymous memory on the order of
	# layer size even with the store itself on a real disk (see SWAP_DISK).
	echo "==> Enabling guest swap on ${SWAP_DISK_BYID}..."
	"${ssh_cmd[@]}" "sudo sh -c 'test -b ${SWAP_DISK_BYID} && mkswap -L tunaos-e2e-swap ${SWAP_DISK_BYID} >/dev/null && swapon ${SWAP_DISK_BYID}' && free -m" ||
		echo "WARN: guest swap not enabled (continuing without it)"

	start_guest_heartbeat

	e2e_phase "Pulling ${imgref} in the guest (bounded 1800s)..."
	if ! timeout 1800 "${ssh_cmd[@]}" "sudo podman pull ${imgref} 2>&1" 2>&1 | tee -a "${SERIAL_LOG}"; then
		echo "ERROR: podman pull failed or timed out" >&2
		return 3
	fi

	local block_setup="" luks_cfg_mount=""
	if [[ "$LUKS" -eq 1 ]]; then
		block_setup="--block-setup tpm2-luks"
		# bootc refuses --block-setup tpm2-luks unless the image's install
		# config opts in: "Block setup Tpm2Luks is not enabled in
		# installation config" (attempt 11, iso-builder run 31125136026 —
		# it wiped /dev/vda and stopped one line later). Stock images ship
		# no such opt-in, and it is install-time POLICY, not image content:
		# stage a config drop-in on the scratch disk and bind-mount it into
		# the installing container instead of mutating the image. "direct"
		# stays in the list so the default path remains enabled too.
		"${ssh_cmd[@]}" "printf '[install]\nblock = [\"direct\", \"tpm2-luks\"]\n' | sudo tee /var/lib/containers/tbox-install-luks.toml >/dev/null" || {
			echo "ERROR: could not stage the bootc install-config drop-in" >&2
			return 3
		}
		luks_cfg_mount="-v /var/lib/containers/tbox-install-luks.toml:/usr/lib/bootc/install/90-tbox-luks.toml:ro"
	fi
	echo "==> Running bootc install to-disk on /dev/vda..."
	# The canonical containerized install (bootc docs): privileged, host pid,
	# /dev and the store bind-mounted. The kargs the passphrase-gate path
	# appends post-install are baked here instead — bootc owns the BLS
	# entries it writes, and --karg is the supported way in.
	if ! timeout 1800 "${ssh_cmd[@]}" "sudo podman run --rm --privileged --pid=host \
		-v /var/lib/containers:/var/lib/containers -v /dev:/dev \
		${luks_cfg_mount} \
		--security-opt label=type:unconfined_t \
		${imgref} \
		bootc install to-disk --wipe ${block_setup} \
		--karg console=ttyS0,115200n8 --karg rd.plymouth=0 --karg plymouth.enable=0 \
		/dev/vda 2>&1" 2>&1 | tee -a "${SERIAL_LOG}"; then
		echo "ERROR: bootc install to-disk failed or timed out" >&2
		return 3
	fi
	"${ssh_cmd[@]}" "sudo pkill -f tunaos-e2e-heartbeat" >/dev/null 2>&1 || true

	if [[ "$LUKS" -eq 1 ]]; then
		"${scp_cmd[@]}" "${script_dir}/lib/e2e-assert.sh" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-assert.sh"
		"${scp_cmd[@]}" "${script_dir}/e2e-luks-checks.sh" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-luks-checks.sh"
		local luks_check_output
		luks_check_output=$("${ssh_cmd[@]}" "TEST_LIB_DIR=${GUEST_HOME} bash ${GUEST_HOME}/e2e-luks-checks.sh" 2>&1) || true
		echo "$luks_check_output" | tee -a "$LUKS_EVIDENCE_LOG"
		if echo "$luks_check_output" | grep -q "^ok - installed disk has a crypto_LUKS partition"; then
			record_luks_evidence "TUNAOS_LUKS_E2E_ENCRYPTED_DISK_CONFIRMED"
		else
			echo "ERROR: installed disk has no crypto_LUKS partition" >&2
			return 3
		fi
		# bootc enrolls the TPM at install time, so unlike the fisherman
		# path the token's absence here would mean the enrollment failed.
		if echo "$luks_check_output" | grep -q "^ok - LUKS header has a systemd-tpm2 enrollment token"; then
			record_luks_evidence "TUNAOS_LUKS_E2E_TPM_ENROLLMENT_CONFIRMED"
		else
			echo "ERROR: bootc tpm2-luks install has no systemd-tpm2 enrollment token" >&2
			return 3
		fi
	fi

	# Best-effort: bootc already baked the kargs; this run is for the ESP
	# evidence dump (and is a no-op on the karg side).
	append_installed_serial_kargs

	echo "==> bootc install complete. Shutting down..."
	poweroff_and_wait_vm

	# Same discipline as the fisherman path: the installed-boot gate must
	# never match live-environment output.
	mv -f "$SERIAL_LOG" "$LIVE_SERIAL_LOG"
	: >"$SERIAL_LOG"

	# ── TPM auto-unlock gate ─────────────────────────────────────────────
	if [[ "$LUKS" -eq 1 ]]; then
		# swtpm exits when its QEMU disconnects; restart it on the SAME
		# state dir so the sealed key still unseals.
		local tpid
		tpid=$(cat "$TPM_PIDFILE" 2>/dev/null || true)
		if [[ -z "$tpid" ]] || ! kill -0 "$tpid" 2>/dev/null; then
			echo "==> Restarting swtpm with preserved state for the unlock boot..."
			start_swtpm keep || return 77
		fi
	fi
	e2e_phase "Booting installed disk (TPM auto-unlock), expecting a login prompt..."
	# shellcheck disable=SC2086  # TPM_ARGS is intentionally word-split (empty unless --luks)
	reset_qemu_sockets
	"$QEMU" -name "tunaos-iso-e2e-installed" -machine "$QEMU_MACHINE" -cpu "$CPU_ARG" \
		-accel "$ACCEL" -m "$MEMORY" -smp "$CPUS" \
		${TPM_ARGS} \
		-drive "if=pflash,format=raw,readonly=on,file=${UEFI_CODE}" \
		-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
		-drive "if=none,id=disk,file=${INSTALL_DISK},format=qcow2" \
		-device virtio-blk-pci,drive=disk,bootindex=0 \
		-netdev "user,id=net0" -device virtio-net-pci,netdev=net0 \
		-monitor "unix:${MONITOR_SOCK},server,nowait" \
		"${E2E_SERIAL_ARGS[@]}" \
		"${QEMU_GPU_ARGS[@]}" \
		-pidfile "$QEMU_PIDFILE" -daemonize

	# Generic images carry no TUNAOS_DESKTOP_CONTRACT service; the gate is
	# the serial getty (console=ttyS0 spawns serial-getty@ttyS0) or a
	# reached systemd target. A locked root never gets there — the boot
	# hangs in the initramfs at the cryptsetup prompt instead.
	local deadline=$(($(date +%s) + TIMEOUT))
	while (($(date +%s) < deadline)); do
		if grep -qaE "login:|Reached target.*(Graphical|Multi-User)" "$SERIAL_LOG" 2>/dev/null; then
			echo "==> Installed system booted (root auto-unlocked via TPM)"
			record_luks_evidence "TUNAOS_LUKS_E2E_PASS encrypted=1 tpm_unlock=1 installed_boot=1 desktop_contract=0"
			screenshot "30-installed" || true
			return 0
		fi
		if [[ -f "$QEMU_PIDFILE" ]] && ! kill -0 "$(cat "$QEMU_PIDFILE")" 2>/dev/null; then
			echo "ERROR: installed VM exited during boot" >&2
			return 4
		fi
		sleep 5
	done
	echo "ERROR: installed system did not reach a login prompt within ${TIMEOUT}s" >&2
	echo "--- last 50 lines of installed-boot serial ---" >&2
	tail -50 "$SERIAL_LOG" 2>/dev/null >&2 || true
	screenshot "installed-desktop-failed" || true
	return 4
}

# Run bootc install-to-disk via SSH, then reboot and verify the installed system.
# This replaces the Anaconda kickstart approach (TunaOS uses bootc, not anaconda).
run_install() {
	record_luks_evidence "TUNAOS_LUKS_E2E_INSTALL_STARTED luks=${LUKS}"
	# Film the install. Started here rather than at boot so the recording is
	# the install itself, not the minutes of live-ISO boot that precede it,
	# and stopped by cleanup_vm's EXIT trap so it ends however the cell ends.
	#
	# Best-effort throughout: record-timelapse.sh returns 0 when it cannot
	# capture (no ffmpeg, or a virgl host where screendump has no surface), so
	# a cell that installs correctly but cannot be filmed stays green.
	TIMELAPSE_DIR="${OUTPUT_DIR}/timelapse"
	bash "${SCRIPT_DIR}/record-timelapse.sh" start "$MONITOR_SOCK" "$TIMELAPSE_DIR" || true
	echo "==> Waiting up to 60s for SSH..."
	for _ in $(seq 1 30); do
		check_ssh && break
		sleep 2
	done
	check_ssh || {
		echo "ERROR: SSH not available" >&2
		# One shot with full verbosity before giving up. The retry loop above
		# is deliberately quiet-ish; this is the frame that gets read when the
		# cell is triaged, and it costs one connection attempt.
		echo "--- ssh -vvv (final attempt, for diagnosis) ---" >&2
		sshpass -p live ssh -vvv \
			-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
			-o ConnectTimeout=10 liveuser@127.0.0.1 -p "$SSH_PORT" true 2>&1 |
			tail -30 >&2 || true
		echo "--- guest-side sshd evidence from serial ---" >&2
		grep -aiE "ssh\.service|sshd|host keys" "$SERIAL_LOG" 2>/dev/null |
			tr -d '\r' | tail -10 >&2 || true
		return 5
	}

	# Transport-aware guest access, resolved by the check_ssh loop above
	# (keepalive rationale on E2E_SSH_OPTS; the ssh -p / scp -P split and
	# transport selection live in the Guest SSH transport section). This is
	# the command the multi-GB image transfer below uses, so it is the one
	# that actually hung the runners in #939.
	local ssh_cmd=("${GUEST_SSH[@]}")
	local scp_cmd=("${GUEST_SCP[@]}")

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
	# Does THIS IMAGE ship fisherman? Probed once, before the override lands,
	# because two separate decisions read it and they need different answers.
	#
	# Generic (non-tunaOS) images ship no fisherman. When the caller names
	# the image (TBOX_E2E_IMAGE), install it with plain bootc instead — see
	# run_install_generic. Without a named image the hard error stands:
	# guessing a registry ref from an ISO filename is exactly the mistake
	# the published-image-ref.sh resolver below exists to prevent.
	#
	# That choice is about the image, not about what this function copied onto
	# it a moment ago. Reading it off /usr/local/bin/fisherman *after* the
	# override installs would hand every TBOX_E2E_IMAGE caller the fisherman
	# path instead, and recipe_image below resolves a *tunaOS* ref from
	# VARIANT/FLAVOR — so a caller-named generic image would be silently
	# swapped for a tunaOS one. Probe first, decide, then override.
	local image_has_fisherman=1
	"${ssh_cmd[@]}" "command -v /usr/local/bin/fisherman" &>/dev/null || image_has_fisherman=0
	if [[ "$image_has_fisherman" -eq 0 && -n "${TBOX_E2E_IMAGE:-}" ]]; then
		run_install_generic
		return $?
	fi

	# An image that ships no fisherman ships no installer GUI either: the
	# flatpak that carries the binary is the same one that carries the
	# frontend, and customize-live.sh downgrades a failed install of it to a
	# warning on dev/E2E media (`.enable-sshd`). The override below makes the
	# LUKS install path testable anyway, which is right — but say out loud
	# what this cell then does NOT cover.
	if [[ "$image_has_fisherman" -eq 0 ]]; then
		echo "::warning::live image ships no /usr/local/bin/fisherman (the installer flatpak is missing from the squash) — this cell tests the LUKS install with the caller's binary, not that ISO's own installer"
	fi

	# Install the override BEFORE the presence check below, not after it.
	#
	# This block used to live ~260 lines further down, next to the recipe.
	# That is too late: the check is a hard `return 3`, so on any image that
	# ships no fisherman the run died without ever installing the binary the
	# job had just built for it. guppy:xfce, LUKS run 31131624108:
	#
	#   ERROR: fisherman not found on live image (VARIANT=guppy FLAVOR=xfce)
	#   ERROR: and TBOX_E2E_IMAGE is unset, so the generic bootc path cannot
	#          name an image ref
	#
	# 55 seconds into the LUKS step, after a 65-minute Gentoo build, with
	# FISHERMAN_OVERRIDE=/tmp/fisherman-bin sitting on the runner and the
	# workflow's own "Build fisherman in a golang container" step green
	# immediately above it. All three guppy cells fail this way.
	#
	# Overriding first is also what the flag means: "use this fisherman", not
	# "use this fisherman provided the image already had one". The bundled
	# installer-flatpak fisherman is pinned to a release, which is why the
	# override exists at all.
	if [[ -n "${FISHERMAN_OVERRIDE:-}" && -f "${FISHERMAN_OVERRIDE}" ]]; then
		echo "==> Overriding fisherman with ${FISHERMAN_OVERRIDE}"
		"${scp_cmd[@]}" "${FISHERMAN_OVERRIDE}" "${GUEST_SCP_DEST}:${GUEST_HOME}/fisherman-override"
		# Create the directory separately rather than letting `install -D` do
		# it. Now that the override also has to work on an image that shipped
		# none, /usr/local/bin may not exist — and on the ostree layout
		# /usr/local is a symlink to a ../var/usrlocal that the image does not
		# contain, where mkdir -p (which is what -D uses) refuses to create
		# *through* a dangling symlink and dies with the confusing
		#
		#   mkdir: cannot create directory '/usr/local': File exists
		#
		# `readlink -m` canonicalises without requiring the path to exist, so
		# this creates /var/usrlocal/bin on the symlinked layout and
		# /usr/local/bin on the plain one, and the install below resolves
		# through the symlink either way. Same trick, same reason, as the
		# symlink customize-live.sh makes at build time.
		"${ssh_cmd[@]}" "sudo mkdir -p \$(readlink -m /usr/local/bin)"
		"${ssh_cmd[@]}" "sudo install -m0755 ${GUEST_HOME}/fisherman-override /usr/local/bin/fisherman"
	fi

	if ! "${ssh_cmd[@]}" "command -v /usr/local/bin/fisherman" &>/dev/null; then
		echo "ERROR: fisherman not found on live image (VARIANT=${VARIANT:-} FLAVOR=${FLAVOR:-})" >&2
		# Only true when the caller named no image: with TBOX_E2E_IMAGE set,
		# an image that shipped no fisherman took the generic path above, so
		# reaching here means the override clobbered a binary that was there.
		if [[ -z "${TBOX_E2E_IMAGE:-}" ]]; then
			echo "ERROR: and TBOX_E2E_IMAGE is unset, so the generic bootc path cannot name an image ref" >&2
		fi
		if [[ -n "${FISHERMAN_OVERRIDE:-}" ]]; then
			echo "ERROR: FISHERMAN_OVERRIDE=${FISHERMAN_OVERRIDE} was set but did not land —" >&2
			echo "ERROR: $([[ -f "${FISHERMAN_OVERRIDE}" ]] && echo 'the file exists, so the scp/install above failed' || echo 'that path does not exist on the runner')" >&2
		fi
		return 3
	fi

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
	# The published ref is NOT always ghcr.io/tuna-os/<variant>:<flavor>.
	# build-config.yml gives bonito-rawhide `publish_name: bonito` +
	# `tag_suffix: rawhide`, so it ships as bonito:<flavor>-rawhide; flounder-sid
	# is flounder:<flavor>-sid. Constructing the ref by hand here meant we probed
	# the embedded offline store for a name it never contained, concluded the
	# image was absent, and fell back to a network pull of a tag that does not
	# exist — four retries ten minutes apart, then a 40-minute-late failure that
	# looked like a flaky registry. All nine such cells had already passed their
	# live-ISO checks ("13 passed, 0 failed") before this hit.
	#
	# published-image-ref.sh is the same resolver build-variant.yml and
	# publish-iso-groups.yml use, so there is one definition of the mapping.
	local published_ref=""
	if ! published_ref=$(
		TUNAOS_BUILD_CONFIG="${SCRIPT_DIR}/../.github/build-config.yml" \
			"${SCRIPT_DIR}/published-image-ref.sh" "${VARIANT:-}" "${FLAVOR:-}" ghcr 2>/dev/null
	) || [[ -z "$published_ref" ]]; then
		published_ref="ghcr.io/tuna-os/${VARIANT:-}:${FLAVOR:-}"
		# Loud, because this fallback is silently wrong for exactly the variants
		# the resolver exists to handle, and a quiet wrong ref costs 40 minutes.
		echo "WARNING: published-image-ref.sh failed (is yq installed?);" >&2
		echo "WARNING: guessing ${published_ref}. This is WRONG for any variant" >&2
		echo "WARNING: with publish_name/tag_suffix set in build-config.yml." >&2
	fi

	local target_imgref="$published_ref"
	local local_ref="localhost/${VARIANT:-}:${FLAVOR:-}" # dev=1 ISO
	local prod_ref="$published_ref"                      # production ISO
	local recipe_image=""                                # set below after probing the VM
	local composefs_backend="false" bootloader="grub2" root_filesystem="xfs"
	# Probed from IMAGE CONTENT, never from the variant name. This used to be
	# `[[ "$VARIANT" == "grouper" ]]`, so sailfin, marlin, flounder,
	# flounder-sid, guppy and gurnard — every other composefs variant — were
	# installed down the ostree/grub2 path they cannot boot. See
	# probe_image_backend() in scripts/lib/backend.sh (tunaOS#954).
	# Probe the image that will actually be INSTALLED. In the dev/e2e flow that
	# is the locally rebuilt one, and the published tag may be months stale or
	# absent entirely for a variant whose Gate has been failing — probing it
	# would answer for an artifact nobody is testing.
	local _probe _probe_ref="$target_imgref"
	if podman image exists "$local_ref" 2>/dev/null; then
		_probe_ref="$local_ref"
	fi
	if _probe=$(probe_image_backend "$_probe_ref" 2>/dev/null); then
		echo "==> image probe: $(echo "$_probe" | tr '\n' ' ')"
		if grep -q '^BACKEND=composefs-native$' <<<"$_probe"; then
			composefs_backend="true"
			bootloader="systemd"
		fi
		# SEALED decides the ROOT FILESYSTEM, and it is a separate question
		# from the backend — which is why it gets its own branch rather than
		# riding along inside the one above.
		#
		# A composefs-sealed rootfs is verified with fs-verity. XFS has no
		# fs-verity, so a sealed image installed onto XFS fails
		# initrd-switch-root and lands in a dracut emergency shell — see the
		# warning in system_files/usr/lib/bootc/install/00-tunaos.toml and
		# tuna-os/wootc payload/deployer/deploy.sh. ext4 is the proven sealed
		# filesystem (btrfs has fs-verity but its ostree deployment fails to
		# mount, wootc#35).
		#
		# Sealing does NOT imply composefs-native: branch 1 of the probe
		# deliberately keeps sealed images that ship a bootupd payload on the
		# ostree path, so `BACKEND=ostree SEALED=1` is a real combination and
		# it still needs ext4. Keying the filesystem off the backend would get
		# exactly those images wrong.
		#
		# scripts/build-qcow2.sh:126-129 has always done this for the Gate's
		# disk image. This recipe hardcoded "xfs" regardless, so the ISO
		# install path and the qcow2 install path disagreed about the same
		# image — the ISO path being the one a user actually takes.
		if grep -q '^SEALED=1$' <<<"$_probe"; then
			root_filesystem="ext4"
		fi
		echo "==> install target: filesystem=${root_filesystem}" \
			"bootloader=${bootloader} composefs=${composefs_backend}"
	else
		echo "ERROR: could not probe ${_probe_ref} for its bootc backend" >&2
		return 3
	fi

	# Does this guest have podman at all? Not a rhetorical question: guppy's
	# base (Containerfile.gentoo) emerges app-containers/skopeo — which is what
	# bootc's containers-image-proxy actually shells out to — and never emerges
	# app-containers/podman or app-misc/jq. So on guppy every `sudo podman ...`
	# below answers
	#
	#   sudo: podman: command not found
	#
	# That is not a broken image; bootc reads containers-storage through skopeo
	# and installs fine. But it silently defeated the store probe further down,
	# which had only podman- and jq-shaped questions to ask. Ask once, here, so
	# the dump names the situation instead of printing it a dozen times and
	# leaving the reader to infer it from a missing "Found" line.
	local guest_has_podman=0
	if "${ssh_cmd[@]}" "command -v podman >/dev/null 2>&1" 2>/dev/null; then
		guest_has_podman=1
	else
		echo "==> guest ships no podman (skopeo-only base) — skipping podman store queries;" \
			"the offline store index is read host-side below"
	fi

	# ── Offline store diagnostics (debug: remove once stable) ─────────
	echo "==> Offline store diagnostics:"
	echo "--- store service status ---"
	"${ssh_cmd[@]}" "systemctl status tunaos-offline-store.service 2>&1 || true" || true
	echo "--- store.squashfs.img exists? ---"
	"${ssh_cmd[@]}" "ls -la /run/initramfs/live/LiveOS/store.squashfs.img 2>&1 || echo '(not found)'" || true
	echo "--- manual mount attempt (fallback) ---"
	"${ssh_cmd[@]}" "sudo mkdir -p /var/lib/superiso-store && sudo mount -o ro,nodev /run/initramfs/live/LiveOS/store.squashfs.img /var/lib/superiso-store 2>&1 || echo '(mount failed)'" || true
	echo "--- mount table (superiso) ---"
	"${ssh_cmd[@]}" "findmnt /var/lib/superiso-store 2>&1 || echo '(not mounted)'" || true
	# Force podman to re-read storage backends after the offline store is
	# mounted. Without this, podman may still use stale in-memory state
	# from before the mount, causing image exists / pull to miss the
	# additional store entirely (observed on Gentoo-based variants where
	# the offline-store.service sometimes races with podman's init).
	if [[ "$guest_has_podman" -eq 1 ]]; then
		"${ssh_cmd[@]}" "sudo podman system renumber 2>&1 || true" || true
	fi
	echo "--- primary storage.conf ---"
	"${ssh_cmd[@]}" "cat /etc/containers/storage.conf 2>&1 || echo '(not found)'" || true
	echo "--- offline store layout ---"
	"${ssh_cmd[@]}" "sudo ls -la /var/lib/superiso-store/ 2>&1 || true" || true
	"${ssh_cmd[@]}" "sudo ls -la /var/lib/superiso-store/overlay-images/ 2>&1 || echo '(no overlay-images)'" || true
	"${ssh_cmd[@]}" "sudo cat /var/lib/superiso-store/storage.lock 2>&1 || echo '(no storage.lock)'" || true
	if [[ "$guest_has_podman" -eq 1 ]]; then
		echo "--- effective storage driver ---"
		"${ssh_cmd[@]}" "sudo podman info 2>&1 | grep -i graphdriver || echo 'podman info failed'" || true
		echo "--- podman images (all) ---"
		"${ssh_cmd[@]}" "sudo podman images 2>&1 || echo '(empty or error)'" || true
	fi

	# skipjack fails here in a way the dump above cannot explain: the store is
	# mounted, storage.conf lists it in additionalimagestores, overlay-images/
	# holds an image directory and images.json — and `podman images` is still
	# empty. Structurally identical to a passing cell, so comparing the two
	# dumps does not converge.
	#
	# These two do. podman logs at debug level *why* it drops an additional
	# image store (driver mismatch, unreadable lock, version skew); images.json
	# is ~1 KB and states the names actually recorded, which distinguishes
	# "store ignored" from "image recorded under a name we never probe".
	if [[ "$guest_has_podman" -eq 1 ]]; then
		echo "--- why podman does or does not see the additional store ---"
		"${ssh_cmd[@]}" "sudo podman --log-level=debug images 2>&1 \
			| grep -iE 'additional|superiso|store|driver' | head -40 \
			|| echo '(no matching debug lines)'" || true
	fi

	# Read the store's index ONCE, and keep it: this is both the diagnostic dump
	# and the input to the probe below, so what the log shows is exactly what
	# the decision was made from.
	local img_json="/var/lib/superiso-store/overlay-images/images.json"
	local store_images_json=""
	store_images_json="$("${ssh_cmd[@]}" "sudo cat ${img_json} 2>/dev/null" 2>/dev/null || true)"
	echo "--- names recorded in the offline store ---"
	printf '%s\n' "${store_images_json:-(unreadable)}"

	# Probe the guest's containers-storage for a locally-available image.
	# Try podman image exists first (primary store), then fall back to
	# inspecting the offline store's images.json directly.  podman image
	# exists sometimes misses images in additional stores when the overlay
	# driver / fuse-overlayfs configuration inside the VM differs from the
	# host that packed the store (observed on Gentoo-based variants).
	local found_local=0 found_ref=""
	for candidate_ref in "$prod_ref" "$local_ref"; do
		echo "==> Probing for ${candidate_ref}..."
		if [[ "$guest_has_podman" -eq 1 ]] &&
			"${ssh_cmd[@]}" "sudo podman image exists '${candidate_ref}'" 2>/dev/null; then
			found_local=1
			found_ref="$candidate_ref"
			break
		fi
		# Fallback: the offline store's own index, parsed on the HOST.
		#
		# This used to run `sudo jq` in the guest, which asks the guest for a jq
		# it may not have. guppy has neither jq nor podman (see the
		# skopeo-only note above), so on that variant BOTH probes were
		# unrunnable — each exiting 127 — and a store that records
		# `ghcr.io/tuna-os/guppy:gnome` verbatim read as "image absent". The
		# cell then spent four minutes on the SSH transfer the block below
		# documents as impossible and died on `scp: write remote ...: Failure`,
		# ~2.5 hours into the job. guppy:gnome, LUKS run 31134373523.
		#
		# The guest only has to supply `cat`, which the dump above proves it
		# can; jq runs where jq is a declared dependency.
		if store_records_image "$store_images_json" "$candidate_ref"; then
			echo "==> Found ${candidate_ref} in offline store images.json (podman query missed it)"
			# This used to deliberately NOT set found_local, on the theory that
			# podman/bootc could not resolve the image from the additional
			# store anyway, so it was better to "fall through to the network
			# pull". Two things were wrong with that. The else branch has not
			# been a network pull for some time — it is an SSH copy of a
			# multi-GB tar. And that copy cannot succeed: it lands in
			# /home/liveuser, which is the live overlay's upperdir, which is a
			# tmpfs (`tbox-overlay ... size=8388608k`) on a 4096M guest with no
			# swap. Pushing a ~4.9G image into ~2.9G of real memory OOMs the
			# guest every time. Measured, not inferred — see #941.
			#
			# So preferring the store is strictly better even when podman's
			# query missed: if bootc cannot read it either we get a fast, clear
			# failure, instead of a guaranteed dead guest ~2.5 minutes in.
			found_local=1
			found_ref="$candidate_ref"
			break
		fi
	done

	if [[ "$found_local" -eq 1 ]]; then
		if [[ "$composefs_backend" == "false" && "$found_ref" == "$prod_ref" ]]; then
			echo "==> Found canonical offline image ${found_ref} — using Fisherman bootcDirect (no OCI copy)"
			# Leave image empty. Fisherman then calls bootc directly and derives
			# --source-imgref containers-storage:<targetImgref>, reading the
			# embedded store without exporting/reimporting the full image.
			recipe_image=""
		else
			echo "==> Found local image ${found_ref} in offline store — using containers-storage transport"
			recipe_image="containers-storage:${found_ref}"
		fi
	else
		# LAST RESORT, AND IT USUALLY FAILS. Read this before relying on it.
		#
		# The comment here used to claim SSH port-forwarding is "a TCP tunnel,
		# immune to SLIRP NAT PMTU issues". Both halves are wrong. Port 2222 is
		# a QEMU `hostfwd` on `-netdev user`, so it traverses SLIRP like
		# everything else — and SLIRP is not what breaks this anyway.
		#
		# What breaks it is the destination. The tar lands in /home/liveuser,
		# i.e. the live overlay's upperdir, which is a tmpfs:
		#
		#   tbox-overlay /run/tbox-overlay tmpfs rw,size=8388608k
		#   LiveOS_rootfs / overlay ... upperdir=/run/tbox-overlay/upper
		#
		# df reports 8.0G free on / because that is the tmpfs's ADVERTISED
		# size. The guest has 3903M of RAM and no swap. Copying a ~4.9G image
		# into ~2.9G of usable memory invokes the OOM killer, every time,
		# regardless of transport or MTU:
		#
		#   rtkit-daemon invoked oom-killer: ... global_oom
		#   Out of memory: Killed process 1622 (niri)
		#
		# Reproduced on hosted CI (2m34s, 2m35s) and on bare metal with no
		# SLIRP pathology and a far faster link (2m54s) — the timing tracks
		# bytes written, not network conditions. See #941.
		#
		# The fix is to use the already-mounted scratch disk for the fallback,
		# not to increase timeouts or retry a write into the RAM-backed overlay.
		echo "==> No local image in offline store — transferring from host via SSH"
		local host_img="localhost/${VARIANT:-}:${FLAVOR:-}"
		local host_tar="/tmp/luks-image-${VARIANT:-}-${FLAVOR:-}.tar"
		local guest_tar_dir="/var/lib/containers/tunaos-e2e-transfer"
		local guest_tar="${guest_tar_dir}/${host_tar##*/}"
		if podman image exists "$host_img" 2>/dev/null; then
			echo "==> Saving $host_img on host..."
			podman save "$host_img" -o "$host_tar"

			# The scratch disk is mounted at /var/lib/containers above. Give the
			# live user a temporary directory there so scp writes to disk rather
			# than the RAM-backed GUEST_HOME overlay tmpfs. The previous destination
			# caused multi-GB images to exhaust guest memory (#882).
			"${ssh_cmd[@]}" "sudo install -d -o liveuser -g liveuser ${guest_tar_dir}" || {
				echo "ERROR: scratch-disk transfer directory could not be prepared" >&2
				rm -f "$host_tar" || true
				return 3
			}

			# Bounded, like the fisherman call below. This is a multi-GB copy
			# over a QEMU SLIRP hostfwd, so it is legitimately slow — but the
			# failure mode it had was not slowness, it was silence: no output
			# between the line above and the runner being killed hours later.
			# The workflow's --timeout does not cover this; that is a PER-PHASE
			# timeout (see the usage text above) consulted only by the
			# readiness wait and the installed-boot wait.
			e2e_phase "Transferring image to guest (this may take a few minutes)..."
			if ! timeout 1800 "${scp_cmd[@]}" "$host_tar" \
				"${GUEST_SCP_DEST}:${guest_tar}"; then
				echo "ERROR: image transfer to guest timed out or failed" >&2
				rm -f "$host_tar" || true
				return 3
			fi
			echo "==> Loading image into guest podman..."
			if timeout 1800 "${ssh_cmd[@]}" "sudo podman load -i ${guest_tar} 2>&1" 2>&1 | tee -a "${SERIAL_LOG}"; then
				echo "==> Image loaded, using local containers-storage ref"
				recipe_image="containers-storage:${host_img}"
			else
				echo "ERROR: podman load failed on guest"
				return 3
			fi
			"${ssh_cmd[@]}" "sudo rm -f ${guest_tar}" || true
			rm -f "$host_tar" || true
		else
			echo "ERROR: host image $host_img not found — was ISO build successful?"
			return 3
		fi
	fi

	# tpm2-luks-passphrase with a KNOWN test passphrase: the first-boot
	# enrollment (fisherman first-boot oneshot) means the first installed
	# boot still needs a key at the prompt; a known passphrase lets the E2E
	# inject it deterministically, after which TPM auto-unlock takes over.
	local encryption_json='{"type": "none"}'
	local E2E_LUKS_PASS="tunaos-e2e-luks"
	[[ "$LUKS" -eq 1 ]] && encryption_json="{\"type\": \"tpm2-luks-passphrase\", \"passphrase\": \"${E2E_LUKS_PASS}\"}"

	# (The FISHERMAN_OVERRIDE install used to be here. It now runs before the
	# presence check near the top of this function — see the comment there.
	# Doing it at this point meant an image that shipped no fisherman never
	# reached it, which is exactly the case the override is for.)

	local RECIPE_LOCAL="${OUTPUT_DIR}/e2e-recipe.json"
	cat >"$RECIPE_LOCAL" <<EOF
{
  "disk": "/dev/vda",
  "filesystem": "${root_filesystem}",
  "image": "${recipe_image}",
  "targetImgref": "${target_imgref}",
  "composeFsBackend": ${composefs_backend},
  "bootloader": "${bootloader}",
  "hostname": "tunaos-e2e",
  "encryption": ${encryption_json},
  "flatpaks": []
}
EOF
	echo "==> Uploading fisherman recipe..."
	"${scp_cmd[@]}" "$RECIPE_LOCAL" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-recipe.json"

	# ── Swap on, before anything allocates ───────────────────────────────
	# See SWAP_DISK: podman's copy of the exported OCI layout into the
	# install-time scratch store allocates on the order of the image size,
	# and a live guest has no swap at all, so the OOM killer takes podman
	# and fisherman reports the install as `signal: killed`. Give the kernel
	# somewhere to page those cold buffers before fisherman starts.
	#
	# Best-effort by design: a guest without the disk (an older ISO booted by
	# hand, a future topology change) should still install, just with the old
	# no-swap headroom. Never write this into the guest's fstab: the disk is
	# attached to the install boot only.
	echo "==> Enabling guest swap on ${SWAP_DISK_BYID}..."
	"${ssh_cmd[@]}" "sudo sh -c 'test -b ${SWAP_DISK_BYID} && mkswap -L tunaos-e2e-swap ${SWAP_DISK_BYID} >/dev/null && swapon ${SWAP_DISK_BYID}' && free -m" ||
		echo "WARN: guest swap not enabled (continuing without it)"

	start_guest_heartbeat

	e2e_phase "Running fisherman ${GUEST_HOME}/e2e-recipe.json..."
	# Bound with `timeout` as a safety net; the image is already local at
	# this point so this should only cover the actual install steps, not a
	# network pull.
	#
	# 1800s was too tight for the largest images. bonito:kde is 9.1 GB in 64
	# layers, and `bootc install to-filesystem` writing that into an encrypted
	# xfs volume inside a nested QEMU guest ran for 25 minutes and was still
	# going when the timer fired — no stall, just a big image on slow virtual
	# storage. Raised, and overridable for a cell that legitimately needs more.
	local install_timeout="${TUNAOS_E2E_INSTALL_TIMEOUT:-3600}"
	timeout "$install_timeout" "${ssh_cmd[@]}" "sudo /usr/local/bin/fisherman ${GUEST_HOME}/e2e-recipe.json 2>&1" 2>&1 | tee -a "${SERIAL_LOG}" || {
		rc=$?
		if [[ $rc -eq 0 ]]; then
			true
		elif [[ $rc -eq 124 ]]; then
			# Do NOT name a cause here. This used to read "(likely a stalled
			# podman pull)", directly contradicting the comment above saying
			# the image is already local — and it sent the bonito:kde
			# investigation looking for a network problem that did not exist.
			# The install's own progress lines are the evidence; print the
			# last one instead of guessing.
			echo "ERROR: fisherman install timed out after ${install_timeout}s"
			echo "       last progress line from the guest:"
			grep -E '"type":"(step|substep)"' "${SERIAL_LOG}" | tail -1 |
				sed 's/^/         /' || echo "         (none recorded)"
			echo "       If that line shows work in flight, the image is too big for the"
			echo "       budget — raise TUNAOS_E2E_INSTALL_TIMEOUT. If it is unchanged from"
			echo "       minutes earlier, it is a genuine stall."
			return 3
		else
			echo "ERROR: fisherman install failed (exit $rc)"
			return 3
		fi
	}

	# Install is done; stop the heartbeat so it cannot bleed into the serial
	# log the passphrase gate greps. On the failure paths above we return
	# without this: the VM is torn down there anyway, and a heartbeat that
	# keeps printing right up to the shutdown is the evidence we came for.
	"${ssh_cmd[@]}" "sudo pkill -f tunaos-e2e-heartbeat" >/dev/null 2>&1 || true

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
		"${scp_cmd[@]}" "${script_dir}/lib/e2e-assert.sh" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-assert.sh"
		"${scp_cmd[@]}" "${script_dir}/e2e-luks-checks.sh" "${GUEST_SCP_DEST}:${GUEST_HOME}/e2e-luks-checks.sh"
		local luks_check_output
		luks_check_output=$("${ssh_cmd[@]}" "TEST_LIB_DIR=${GUEST_HOME} bash ${GUEST_HOME}/e2e-luks-checks.sh" 2>&1) || true
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
			# TPM2 auto-unlock is a POST-INSTALL step by design, not the
			# installer's job: systemd-cryptenroll seals to PCRs (7+14) that
			# only exist on the real installed+booted system, so install-time
			# enrollment seals against the wrong state (same model as
			# ublue-os-luks / Fedora Silverblue; bootc-dev/bootc#421). fisherman
			# produces a passphrase-encrypted disk (confirmed above); the owner
			# opts into TPM via `ujust enable-luks-tpm2`. Don't fail install
			# verification on the (correct) absence of an install-time token.
			echo "NOTE: no systemd-tpm2 token yet — TPM auto-unlock is post-install (ujust enable-luks-tpm2)."
		fi
	fi

	# E2E-only kargs on the installed system's BLS entries (the live env can
	# still mount the unencrypted ESP/boot). console=ttyS0 puts kernel output on
	# the serial the gate reads; plymouth.enable=0 makes the initramfs
	# cryptsetup PASSWORD PROMPT appear as serial text ("Please enter
	# passphrase for disk ...") instead of a graphical plymouth prompt — without
	# it luks-first-boot.py never sees the prompt (run 29670982740). Real users
	# still get the plymouth prompt on a display; this is test media only.
	append_installed_serial_kargs

	echo "==> fisherman install complete. Shutting down..."
	poweroff_and_wait_vm

	# The installed-boot gate must never match a marker emitted by the live
	# environment. Preserve the first boot as separate evidence and give QEMU a
	# fresh serial log for the disk boot.
	mv -f "$SERIAL_LOG" "$LIVE_SERIAL_LOG"
	: >"$SERIAL_LOG"

	# ── LUKS passphrase gate ─────────────────────────────────────────────
	# The gate is: the encrypted root unlocks with the install PASSPHRASE and
	# reaches userspace. That is fisherman's job and works on every variant.
	# TPM2 auto-unlock is a SEPARATE, post-install, per-variant test (it seals
	# to PCRs that only exist on the installed system — see docs/LUKS-TPM.md),
	# so it is NOT gated here (see TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK below for
	# the opt-in that does gate it). Boot with a serial socket and inject the
	# passphrase at the cryptsetup prompt; reaching login proves the unlock.
	if [[ "$LUKS" -eq 1 ]]; then
		e2e_phase "LUKS passphrase gate: booting installed disk, injecting passphrase, expecting login..."
		local FB_SERIAL="${OUTPUT_DIR}/installed-serial.sock"
		rm -f "$FB_SERIAL"
		# A TPM IS needed on THIS boot (tunaOS#680): fisherman#48 stages a
		# ConditionFirstBoot oneshot that enrolls systemd-cryptenroll
		# --tpm2-device=auto against the REAL installed system's PCR 7 —
		# measured during exactly this boot, which is the whole point (the
		# old install-time enrollment sealed against the live ISO's PCR 7
		# instead, and never unsealed on the installed system — tunaOS#679/
		# #680). Without a TPM attached here, that oneshot has nothing to
		# enroll against and TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK's later boot
		# would only ever see the passphrase prompt.
		#
		# The install-phase swtpm has already exited — it dies when its own
		# QEMU (fisherman's install VM, just powered off above) disconnects
		# — so it must be restarted against the SAME state dir, exactly like
		# run_install_generic's TPM auto-unlock gate does.
		local tpid
		tpid=$(cat "$TPM_PIDFILE" 2>/dev/null || true)
		if [[ -z "$tpid" ]] || ! kill -0 "$tpid" 2>/dev/null; then
			echo "==> Restarting swtpm with preserved state for the first installed boot..."
			start_swtpm keep || return 77
		fi
		#
		# bootindex=0 on the disk (see also boot_installed) is what makes
		# "boot the thing we just installed" deterministic. Both boots share
		# one OVMF_VARS file, so the installed boot inherits the BootOrder
		# the live-ISO boot left behind, including OVMF's "EFI Internal
		# Shell" entry. An install that writes an EFI variable of its own
		# (bootupd/grub2 variants call efibootmgr, which prepends) lands
		# ahead of the shell and boots; an install that cannot (sailfin:
		# bootctl skips efivars inside the install container) is left with
		# only the auto-enumerated disk option, which BDS appends *after*
		# the shell, so the firmware drops to `Shell>` and the passphrase
		# prompt never appears (run 30732193680). bootindex publishes a
		# QEMU fw_cfg boot order that OVMF applies over the stale NVRAM,
		# putting this disk first and leaving the shell as the last resort.
		reset_qemu_sockets
		# shellcheck disable=SC2086  # TPM_ARGS is intentionally word-split (empty unless --luks)
		"$QEMU" -name "tunaos-iso-e2e-installed" -machine "$QEMU_MACHINE" -cpu "$CPU_ARG" \
			-accel "$ACCEL" -m "$MEMORY" -smp "$CPUS" \
			${TPM_ARGS} \
			-drive "if=pflash,format=raw,readonly=on,file=${UEFI_CODE}" \
			-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
			-drive "if=none,id=disk,file=${INSTALL_DISK},format=qcow2" \
			-device virtio-blk-pci,drive=disk,bootindex=0 \
			-netdev "user,id=net0" -device virtio-net-pci,netdev=net0 \
			-monitor "unix:${MONITOR_SOCK},server,nowait" \
			-serial "unix:${FB_SERIAL},server,nowait" \
			"${QEMU_GPU_ARGS[@]}" -pidfile "$QEMU_PIDFILE" -daemonize || {
			# Without this the launch failure is a bare qemu message and a
			# `set -e` exit, which is how run 31140233496 reported a pidfile
			# collision as an unexplained "exit code 1" with no ERROR line to
			# search for. Name it, and name the usual reason.
			echo "ERROR: QEMU would not start for the LUKS passphrase gate (message above)" >&2
			echo "       A 'cannot lock pid file' there means the install VM outlived" >&2
			echo "       poweroff_and_wait_vm and still holds ${QEMU_PIDFILE}." >&2
			return 5
		}
		# 5th arg: keep draining the serial for up to 300s past login waiting
		# for the desktop contract. See luks-first-boot.py for why.
		python3 "$(dirname "${BASH_SOURCE[0]}")/luks-first-boot.py" \
			"$FB_SERIAL" "$MONITOR_SOCK" "$E2E_LUKS_PASS" 900 300 \
			2>&1 | tee "${OUTPUT_DIR}/installed-serial.log" || {
			echo "ERROR: encrypted disk did not unlock with the passphrase / reach login"
			# Photograph the failure before killing the guest. "Unlock failed"
			# and "unlock failed, and the screen was sitting at a cryptsetup
			# passphrase prompt" are different bugs, and the second one is only
			# ever visible here — the guest is gone one line later.
			screenshot "installed-desktop-failed" || true
			[[ -s "$QEMU_PIDFILE" ]] && kill "$(cat "$QEMU_PIDFILE")" 2>/dev/null || true
			return 4
		}
		# ── Photograph the installed desktop, BEFORE killing the guest ────
		# The desktop contract's liveness test is `systemctl is-active
		# display-manager.service`, which for niri resolves to greetd — so it
		# passes whenever greetd is ACTIVE, whether or not the greeter ever
		# draws a pixel. That is instrumentation, not proof, and it is exactly
		# how run 29645108966 reported a green gate over a black console.
		# A framebuffer capture is the cheapest thing that can contradict it.
		#
		# Ordering matters twice: luks-first-boot.py only returns after its
		# 300s post-login drain, so by here the session has had time to come
		# up; and the kill below destroys the only surface there is to capture.
		screenshot "installed-desktop" || true
		local _shot="absent"
		SCREENSHOT_STDDEV=""
		if screenshot_sane "installed-desktop"; then
			_shot="drawn"
		elif [[ -s "${OUTPUT_DIR}/installed-desktop.png" || -s "${OUTPUT_DIR}/installed-desktop.ppm" ]]; then
			# A capture exists but did not clear the floor. Only call that
			# "blank" if it was actually measured — without ImageMagick
			# screenshot_sane declines to judge, and recording that refusal as
			# a blank screen would invent a product failure out of a missing
			# host package.
			if [[ -n "$SCREENSHOT_STDDEV" ]]; then
				_shot="blank"
			else
				_shot="unmeasured"
			fi
		fi
		[[ -s "$QEMU_PIDFILE" ]] && kill "$(cat "$QEMU_PIDFILE")" 2>/dev/null || true
		record_luks_evidence "TUNAOS_LUKS_E2E_PASS encrypted=1 passphrase_unlock=1 installed_boot=1"

		# `drawn` means SOMETHING rendered — not that this desktop's session is
		# up. A greetd greeter that draws, or a text login prompt, clears the
		# same stddev floor. So this closes the black-console hole and leaves
		# the greeter-drew-but-no-session hole open; the installed system has
		# no SSH, so the `pgrep -x <compositor>` discriminator the live path
		# uses (installer-smoke.yml) is not available here. Score accordingly.
		record_luks_evidence \
			"TUNAOS_LUKS_E2E_INSTALLED_SCREENSHOT rendered=${_shot} stddev=${SCREENSHOT_STDDEV:-na} fatal=0"

		# ── Desktop contract on the INSTALLED system ──────────────────
		# Recorded as its own evidence line, NOT folded into the line above:
		# the workflow gate is `grep -qx 'TUNAOS_LUKS_E2E_PASS encrypted=1
		# passphrase_unlock=1 installed_boot=1'` -- exact-match and anchored,
		# so appending a field would turn every currently-green LUKS cell red
		# on a string mismatch, across every variant and several sessions'
		# work.
		#
		# FATAL as of this commit. The rule the earlier revision set for
		# itself was "get one named run first, then gate on it", because a
		# red result would otherwise be ambiguous between "the desktop does
		# not come up" and "the harvest is wrong". That run now exists twice,
		# on two different families and package managers:
		#
		#   gurnard:pantheon (31232163933)  desktop_contract=ok  apt/lightdm
		#   grouper:xfce     (31232166865)  desktop_contract=ok  apt/lightdm
		#
		# and the harvest was proven in the same arc by its failures: it
		# reported dm_inactive with the DM's own journal tail while lightdm
		# was genuinely crash-looping (#1073), and flipped to ok once the
		# missing X server was installed (#1086). It measures what it claims.
		local _dc="absent"
		if grep -q "LUKS_FIRST_BOOT_DESKTOP_CONTRACT=ok" "${OUTPUT_DIR}/installed-serial.log" 2>/dev/null; then
			_dc="ok"
		elif grep -q "LUKS_FIRST_BOOT_DESKTOP_CONTRACT=fail" "${OUTPUT_DIR}/installed-serial.log" 2>/dev/null; then
			_dc="fail"
		fi
		record_luks_evidence "TUNAOS_LUKS_E2E_DESKTOP_CONTRACT desktop_contract=${_dc} fatal=1"
		case "$_dc" in
		ok) echo "==> Desktop contract PASSED on the installed encrypted system" ;;
		fail)
			echo "WARNING: desktop contract FAILED on the installed system:" >&2
			grep -a "TUNAOS_DESKTOP_CONTRACT_FAIL" "${OUTPUT_DIR}/installed-serial.log" | tr -d '\r' >&2 || true
			;;
		*) echo "WARNING: no desktop contract marker on the installed system (DM likely never started)" >&2 ;;
		esac

		# ── Pixel gate: "DM active" must become "something actually drew" ──
		# All the evidence above this line already exists on every run — the
		# stddev-measured screenshot and the timelapse frames — but it was
		# recorded fatal=0 and gated nothing, which is how a black console
		# shipped under a green cell (run 29645108966). pixel_gate
		# (scripts/lib/pixel-gate.sh) turns the measurable cases into a
		# verdict and names the unmeasurable ones (virgl, no ImageMagick)
		# instead of silently passing them.
		#
		# Stop the timelapse NOW rather than leaving it to cleanup_vm's EXIT
		# trap: the gate needs frame-count.txt while the verdict is being
		# decided. stop is idempotent (the pidfile is consumed; a second
		# assemble recounts the same frames), so cleanup's later stop stays
		# harmless.
		local _frames="" _pixel_line="" _pixel_rc=0
		if [[ -n "${TIMELAPSE_DIR:-}" ]]; then
			bash "${SCRIPT_DIR}/record-timelapse.sh" stop "$TIMELAPSE_DIR" || true
			_frames="$(cat "${TIMELAPSE_DIR}/frame-count.txt" 2>/dev/null || true)"
		fi
		_pixel_line="$(pixel_gate "$_shot" "${SCREENSHOT_STDDEV:-}" "$_frames" "${QEMU_NEEDS_VNC_SURFACE:-0}" "$_dc")" || _pixel_rc=$?
		record_luks_evidence "$_pixel_line"
		if [[ "$_pixel_rc" -ne 0 ]]; then
			if [[ "${TUNAOS_PIXEL_GATE:-1}" == "1" ]]; then
				echo "ERROR: pixel gate FAILED — the encrypted install unlocked and reached" >&2
				echo "       login, but nothing provably rendered (${_pixel_line})." >&2
				echo "       The screenshot and timelapse artifacts are the evidence;" >&2
				echo "       TUNAOS_PIXEL_GATE=0 downgrades this to advisory." >&2
				return 6
			fi
			echo "::warning::pixel gate failed but TUNAOS_PIXEL_GATE=0 — advisory only (${_pixel_line})"
		fi

		# ── Desktop contract verdict ──────────────────────────────────
		# Checked HERE, after the pixel gate, for two reasons. Both evidence
		# lines land on every run regardless of outcome — returning earlier
		# would drop TUNAOS_LUKS_E2E_PIXEL_GATE from exactly the artifacts
		# someone debugging a contract failure needs. And this is the
		# placement that closes the hole the pixel gate cannot see: a greeter
		# that draws clears the stddev floor and passes the pixel gate, while
		# the in-guest contract still reports no session (the
		# greeter-drew-but-no-session case named in the screenshot comment
		# above). That case reaches this line with _pixel_rc=0.
		if [[ "$_dc" != "ok" ]]; then
			if [[ "${TUNAOS_DESKTOP_CONTRACT:-1}" == "1" ]]; then
				echo "ERROR: desktop contract FAILED on the installed system" >&2
				echo "       (desktop_contract=${_dc}) — the encrypted install booted, but the" >&2
				echo "       guest's own DM/session assertions did not pass. installed-serial.log" >&2
				echo "       carries the dm_diag detail; TUNAOS_DESKTOP_CONTRACT=0 downgrades" >&2
				echo "       this to advisory." >&2
				return 7
			fi
			echo "::warning::desktop contract ${_dc} but TUNAOS_DESKTOP_CONTRACT=0 — advisory only"
		fi

		echo "==> LUKS passphrase gate PASSED for ${VARIANT:-}:${FLAVOR:-}"

		# ── Opt-in: TPM2 auto-unlock verification (tunaOS#680) ──────────
		# The passphrase gate above proves fisherman's install-time
		# encryption works; it does NOT prove the first-boot enrollment
		# oneshot (fisherman#48) actually seals a working key, because it
		# never boots the disk a second time. luks-first-boot.py's own
		# docstring says as much: "The SECOND boot (driven by iso-e2e.sh)
		# then proves TPM auto-unlock: no passphrase prompt" — that second
		# boot did not exist until this block. docs/LUKS-TPM.md's variant
		# table has read "_pending E2E_" for TPM2 auto-unlock on every
		# variant because of exactly this gap.
		#
		# Opt-in (default off) rather than folded into the gate above: the
		# passphrase gate alone already runs on every {variant, flavor} cell
		# with build_image=true (luks-e2e.yml's monthly sweep), and a third
		# boot per cell is real added cost + a new failure mode across ~50
		# cells at once. docs/LUKS-TPM.md already describes this as "the
		# per-variant TPM-enrollment test", run separately — this flag is
		# that test, callable from the same harness instead of a
		# reimplementation. A maintainer can wire it into luks-e2e.yml (a
		# workflow_dispatch boolean, or its own scheduled job over a smaller
		# variant set) once satisfied with the added runtime.
		if [[ "${TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK:-0}" == "1" ]]; then
			e2e_phase "TPM auto-unlock verification: rebooting the installed disk with no passphrase..."
			local tpid2
			tpid2=$(cat "$TPM_PIDFILE" 2>/dev/null || true)
			if [[ -z "$tpid2" ]] || ! kill -0 "$tpid2" 2>/dev/null; then
				echo "==> Restarting swtpm with preserved state for the TPM auto-unlock boot..."
				start_swtpm keep || return 77
			fi
			# $SERIAL_LOG was truncated before the passphrase-gate boot
			# above and never reopened (that boot used its own FB_SERIAL
			# socket instead), so it is still empty here — safe to reuse
			# via the same file-chardev E2E_SERIAL_ARGS the generic path's
			# TPM auto-unlock gate uses.
			reset_qemu_sockets
			# shellcheck disable=SC2086  # TPM_ARGS is intentionally word-split (empty unless --luks)
			"$QEMU" -name "tunaos-iso-e2e-installed" -machine "$QEMU_MACHINE" -cpu "$CPU_ARG" \
				-accel "$ACCEL" -m "$MEMORY" -smp "$CPUS" \
				${TPM_ARGS} \
				-drive "if=pflash,format=raw,readonly=on,file=${UEFI_CODE}" \
				-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
				-drive "if=none,id=disk,file=${INSTALL_DISK},format=qcow2" \
				-device virtio-blk-pci,drive=disk,bootindex=0 \
				-netdev "user,id=net0" -device virtio-net-pci,netdev=net0 \
				-monitor "unix:${MONITOR_SOCK},server,nowait" \
				"${E2E_SERIAL_ARGS[@]}" \
				"${QEMU_GPU_ARGS[@]}" -pidfile "$QEMU_PIDFILE" -daemonize || {
				echo "ERROR: QEMU would not start for the TPM auto-unlock verification boot" >&2
				record_luks_evidence "TUNAOS_LUKS_E2E_TPM_AUTOUNLOCK_FAILED reason=qemu-launch"
				return 5
			}
			local tpm_deadline=$(($(date +%s) + TIMEOUT))
			local tpm_ok=0 tpm_saw_prompt=0
			while (($(date +%s) < tpm_deadline)); do
				if grep -qaE "login:|Reached target.*(Graphical|Multi-User)" "$SERIAL_LOG" 2>/dev/null; then
					tpm_ok=1
					break
				fi
				# A passphrase prompt here means the disk is STILL sealed to
				# a passphrase, not the TPM — the oneshot did not enroll (or
				# enrolled against the wrong PCR state). That is a distinct,
				# more actionable failure than a bare timeout, so name it
				# rather than waiting out the full deadline for a boot that
				# is truthfully just stuck at a prompt no one will answer.
				if [[ "$tpm_saw_prompt" -eq 0 ]] && grep -qai "passphrase for disk root" "$SERIAL_LOG" 2>/dev/null; then
					tpm_saw_prompt=1
					echo "==> (still shows a passphrase prompt — TPM enrollment did not take; waiting out the deadline for a clean report)"
				fi
				if [[ -f "$QEMU_PIDFILE" ]] && ! kill -0 "$(cat "$QEMU_PIDFILE")" 2>/dev/null; then
					echo "ERROR: TPM auto-unlock verification VM exited during boot" >&2
					break
				fi
				sleep 5
			done
			screenshot "installed-tpm-autounlock" || true
			[[ -s "$QEMU_PIDFILE" ]] && kill "$(cat "$QEMU_PIDFILE")" 2>/dev/null || true
			mv -f "$SERIAL_LOG" "${OUTPUT_DIR}/installed-tpm-autounlock-serial.log" 2>/dev/null || true
			: >"$SERIAL_LOG"
			if [[ "$tpm_ok" -eq 1 ]]; then
				echo "==> TPM auto-unlock verification PASSED — no passphrase prompt, login reached"
				record_luks_evidence "TUNAOS_LUKS_E2E_TPM_AUTOUNLOCK_CONFIRMED"
			else
				local reason="timeout"
				[[ "$tpm_saw_prompt" -eq 1 ]] && reason="passphrase-still-required"
				echo "ERROR: TPM auto-unlock verification FAILED (${reason}) — see installed-tpm-autounlock-serial.log" >&2
				record_luks_evidence "TUNAOS_LUKS_E2E_TPM_AUTOUNLOCK_FAILED reason=${reason}"
				return 8
			fi
		fi

		return 0
	fi

	e2e_phase "Booting installed system..."
	# Boot from the install disk (remove cdrom). bootindex=0 overrides the
	# BootOrder the live-ISO boot left in the shared OVMF_VARS; see the
	# LUKS passphrase gate above for why the shell wins without it.
	# shellcheck disable=SC2086  # TPM_ARGS is intentionally word-split (empty unless --luks)
	reset_qemu_sockets
	"$QEMU" \
		-name "tunaos-iso-e2e-installed" \
		-machine "$QEMU_MACHINE" \
		-cpu "$CPU_ARG" \
		-accel "$ACCEL" \
		-m "$MEMORY" \
		-smp "$CPUS" \
		${TPM_ARGS} \
		-drive "if=pflash,format=raw,readonly=on,file=${UEFI_CODE}" \
		-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
		-drive "if=none,id=disk,file=${INSTALL_DISK},format=qcow2" \
		-device virtio-blk-pci,drive=disk,bootindex=0 \
		-netdev "user,id=net0,hostfwd=tcp::${SSH_PORT}-:22" \
		-device virtio-net-pci,netdev=net0 \
		-monitor "unix:${MONITOR_SOCK},server,nowait" \
		"${E2E_SERIAL_ARGS[@]}" \
		"${QEMU_GPU_ARGS[@]}" \
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
	e2e_phase "Booting disk image: ${ISO_PATH} (${fmt})"
	echo "==> Accel: ${ACCEL}, CPU: ${CPU_ARG}, MEM: ${MEMORY}M, CPUS: ${CPUS}"

	reset_qemu_sockets
	"$QEMU" \
		-name "tunaos-disk-e2e" \
		-machine "$QEMU_MACHINE" \
		-cpu "$CPU_ARG" \
		-accel "$ACCEL" \
		-m "$MEMORY" \
		-smp "$CPUS" \
		-drive "if=pflash,format=raw,readonly=on,file=${UEFI_CODE}" \
		-drive "if=pflash,format=raw,file=${OVMF_VARS}" \
		-drive "if=none,id=disk,file=${ISO_PATH},format=${fmt}" \
		-device virtio-blk-pci,drive=disk \
		-netdev "user,id=net0,hostfwd=tcp::${SSH_PORT}-:22" \
		-device virtio-net-pci,netdev=net0 \
		-monitor "unix:${MONITOR_SOCK},server,nowait" \
		"${E2E_SERIAL_ARGS[@]}" \
		"${QEMU_GPU_ARGS[@]}" \
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
	# Which contract proves the boot. Base images reach multi-user, not
	# graphical, so their marker is TUNAOS_BASE_CONTRACT_* (see --contract).
	DISK_CONTRACT="${DISK_CONTRACT:-desktop}"
	case "$DISK_CONTRACT" in
	desktop) CONTRACT_PREFIX="TUNAOS_DESKTOP_CONTRACT" ;;
	base) CONTRACT_PREFIX="TUNAOS_BASE_CONTRACT" ;;
	*)
		echo "ERROR: --contract must be 'desktop' or 'base', got '${DISK_CONTRACT}'" >&2
		exit 1
		;;
	esac
	e2e_phase "Waiting up to ${TIMEOUT}s for the ${DISK_CONTRACT} contract marker..."
	deadline=$(($(date +%s) + TIMEOUT))
	rc=2
	while (($(date +%s) < deadline)); do
		# QEMU exiting early means the image didn't boot at all.
		if [[ -f "$QEMU_PIDFILE" ]] && ! kill -0 "$(cat "$QEMU_PIDFILE")" 2>/dev/null; then
			echo "ERROR: VM exited during boot" >&2
			exit 1
		fi
		if grep -qE "${CONTRACT_PREFIX}_(OK|FAIL)" "$SERIAL_LOG" 2>/dev/null; then
			if grep -q "${CONTRACT_PREFIX}_OK" "$SERIAL_LOG" 2>/dev/null; then
				echo "==> ${DISK_CONTRACT} contract passed (serial)"
				rc=0
				harvest_install_checks || rc=1
			else
				echo "ERROR: ${DISK_CONTRACT} contract FAILED:" >&2
				grep "${CONTRACT_PREFIX}_FAIL" "$SERIAL_LOG" | tr -d '\r' >&2
				rc=1
			fi
			break
		fi
		sleep 10
	done
	# Let the display manager finish drawing before capturing evidence.
	# Poll for paint instead of a fixed 30s sleep: under plain virtio-vga the
	# guest renders via llvmpipe and first paint can lag the contract marker
	# by minutes on a 2-4 vCPU runner (tunaOS#581). The verdict above already
	# came from the serial marker, so this is evidence work — a slow or absent
	# paint extends the run, it cannot fail it.
	wait_for_paint "10-ready" || true
	if [[ "$rc" -eq 2 ]]; then
		echo "ERROR: ${DISK_CONTRACT} contract marker was not emitted" >&2
		# Answer WHY in the job log itself, not only in an artifact a human
		# must download: every base Gate on 2026-08-18's nightlies timed out
		# with a painted VGA screen and this branch as the only in-log
		# evidence (sailfin run 32091072257, bonito-rawhide 32090947417).
		# An EMPTY serial log means the console karg routing is broken (the
		# markers went to the screen the Gate photographs); a serial log
		# with kernel printk but no marker means the contract unit itself
		# never ran or never reached the console. The tail makes the two
		# distinguishable at a glance.
		if [[ -s "$SERIAL_LOG" ]]; then
			echo "==> serial log captured $(wc -c <"$SERIAL_LOG") bytes; last 120 lines:" >&2
			tail -n 120 "$SERIAL_LOG" | sed 's/^/serial| /' >&2
		else
			echo "==> serial log is EMPTY — nothing reached ${SERIAL_LOG}: the guest's console= routing never targeted the serial port the Gate captures" >&2
		fi
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
	# Poll for paint so the evidence screenshot — and the screenshot-sanity
	# fallback below, which re-measures the same file — sees the desktop
	# rather than a still-llvmpipe black frame (tunaOS#581). Bounded by
	# TBOX_E2E_PAINT_TIMEOUT; the serial marker, not pixels, stays the gate.
	wait_for_paint "10-ready" || true
	# Serial marker missing is expected when the guest kernel has no serial
	# console support; fall back to verifying the framebuffer actually
	# rendered a screen. Hard failures (blank/absent screenshot) stay fatal
	# so this exit code can gate publishing.
	if [[ "$rc" -ne 0 ]] && ! boot_failed_on_serial && screenshot_sane "10-ready"; then
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
		echo "==> Running installer GUI checks..."
		run_installer_gui_checks || rc=5
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
		"${GUEST_SSH[@]}" \
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
		"${GUEST_SSH[@]}" \
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
