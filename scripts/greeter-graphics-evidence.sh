#!/usr/bin/env bash
# scripts/greeter-graphics-evidence.sh — guest-side evidence for a GDM greeter
# that cannot start (tunaOS#3969).
#
# gdm-login-gate.sh pipes this into the guest (`ssh ... bash -s -- MODE SAMPLES`)
# and keeps the output as an artifact. It only reads; it changes nothing in the
# guest and its exit status never reaches the gate's verdict.
#
# Why it exists. The retained journal of a failed albacore:tuna gate filtered
# lines for `gdm|gnome-shell|mutter`, so the crash showed one frame of a
# 24-frame trace, and nothing recorded which environment the crashing
# gnome-shell ran with. Measured on the shipped stack (mesa 25.2.7, kernel
# 6.12.0-211.67.1.el10_2, QEMU `-vga virtio`, no virgl) the crash needs the
# process to force software rendering: `LIBGL_ALWAYS_SOFTWARE=1` or
# `MESA_LOADER_DRIVER_OVERRIDE=swrast` makes `eglInitialize` on the EGLDevice
# that mutter opens dereference a NULL swrast loader in `drisw_init_screen`.
# What is NOT measured is where that variable comes from in a greeter, and why
# only some boots have it. This script records exactly that, for a boot that
# crashes and for a boot that does not, so the two can be compared.
#
# Usage (inside the guest):
#   greeter-graphics-evidence.sh once          # one report
#   greeter-graphics-evidence.sh sample N      # also poll for greeter processes N times
#
# Test seams: TUNAOS_EVIDENCE_PROC, _SYSFS_DRM, _DEV_DRI and _FLAG point at
# fixtures; every other command is looked up on PATH.
set -u

MODE="${1:-once}"
SAMPLES="${2:-0}"
PROC="${TUNAOS_EVIDENCE_PROC:-/proc}"
SYSFS_DRM="${TUNAOS_EVIDENCE_SYSFS_DRM:-/sys/class/drm}"
DEV_DRI="${TUNAOS_EVIDENCE_DEV_DRI:-/dev/dri}"
FLAG="${TUNAOS_EVIDENCE_FLAG:-/run/tunaos-software-gl}"

# Variables that choose or force a renderer, plus the ones that say how the
# process was started. Nothing else is printed, so no credential can leak.
ENV_RE='^(LIBGL_|MESA_|GALLIUM_|EGL_|__EGL_|__GLX_|GBM_|MUTTER_|COGL_|CLUTTER_|WLR_|KWIN_|LD_|XDG_SESSION_|XDG_RUNTIME_DIR=|DBUS_SESSION_BUS_ADDRESS=|GNOME_SHELL_SESSION_MODE=|WAYLAND_DISPLAY=|HOME=)'
# The greeter chain, in start order.
PROCESSES='gdm-session-wor gdm-wayland-ses gnome-session-b dbus-daemon gnome-shell'

section() { printf '\n==> %s\n' "$1"; }

report_identity() {
	section "identity"
	date -u +%Y-%m-%dT%H:%M:%SZ
	uname -r
	if command -v rpm >/dev/null 2>&1; then
		rpm -q mesa-libEGL mesa-dri-drivers mesa-libgbm libglvnd-egl libdrm \
			mutter gnome-shell gdm gnome-session systemd kernel-core 2>&1 || true
	fi
	if command -v dpkg-query >/dev/null 2>&1; then
		dpkg-query -W libegl-mesa0 libgbm1 mesa-libgallium libdrm2 mutter \
			gnome-shell gdm3 gnome-session systemd 2>&1 || true
	fi
	if [[ -r "${PROC}/cmdline" ]]; then
		printf 'kernel command line: '
		tr '\0' ' ' <"${PROC}/cmdline"
		printf '\n'
	fi
}

report_drm() {
	section "DRM devices and renderer inputs"
	ls -l "$DEV_DRI" 2>&1 || true
	local card driver
	for card in "$SYSFS_DRM"/card[0-9]*; do
		[[ -e "$card" ]] || continue
		case "${card##*/}" in *-*) continue ;; esac
		driver="$(basename "$(readlink -f "$card/device/driver" 2>/dev/null)" 2>/dev/null)"
		printf '%s driver=%s vendor=%s device=%s\n' "${card##*/}" "$driver" \
			"$(cat "$card/device/vendor" 2>/dev/null)" "$(cat "$card/device/device" 2>/dev/null)"
	done
	dmesg 2>/dev/null | grep -E '\[drm\]|simpledrm|virtio_gpu|vgaarb|fb0' || true
}

report_software_gl() {
	section "software-GL decision (tunaos-software-gl-detect)"
	ls -l "$FLAG" 2>&1 || true
	systemctl status tunaos-software-gl-detect.service --no-pager 2>&1 | head -n 12 || true
	# The detector is `dmesg | grep -Eq ...` under `pipefail`. Replay that exact
	# pipeline: grep -q leaves at its first match, and a dmesg that is still
	# writing then dies of SIGPIPE (exit 141), which pipefail reports as "no
	# match" although the line is there. The count below reads the whole stream.
	local i rc
	for i in 1 2 3 4 5; do
		(
			set -o pipefail
			dmesg 2>/dev/null | grep -Eq '\[drm\] features:.*-virgl([[:space:]]|$)'
		)
		rc=$?
		printf 'detector pipeline replay %s: exit=%s\n' "$i" "$rc"
	done
	printf 'dmesg bytes: %s\n' "$(dmesg 2>/dev/null | wc -c)"
	printf -- '-virgl lines (whole stream): %s\n' \
		"$(dmesg 2>/dev/null | grep -Ec '\[drm\] features:.*-virgl([[:space:]]|$)')"
}

report_managers() {
	section "system manager environment"
	systemctl show-environment 2>&1 || true
	section "user managers and sessions"
	systemctl list-units --all --no-pager --no-legend 'user@*' 'user-runtime-dir@*' 2>&1 || true
	loginctl list-sessions --no-legend 2>&1 || true
}

# print_process_environment PIDDIR — one greeter process and its renderer env.
print_process_environment() {
	local dir="$1" comm uid
	comm="$(cat "$dir/comm" 2>/dev/null)"
	uid="$(awk '/^Uid:/ { print $2 }' "$dir/status" 2>/dev/null)"
	printf -- '--- pid %s comm=%s uid=%s\n' "${dir##*/}" "$comm" "$uid"
	tr '\0' '\n' <"$dir/environ" 2>/dev/null | grep -E "$ENV_RE" || echo "(no renderer or session variables)"
}

# scan_greeter_processes — print each greeter-chain process once.
declare -A SEEN=()
scan_greeter_processes() {
	local dir comm key found=0
	for dir in "$PROC"/[0-9]*; do
		# `read` is a builtin: this loop visits every process, forty times, and
		# must not fork once per process.
		read -r comm <"$dir/comm" 2>/dev/null || continue
		case " $PROCESSES " in *" $comm "*) ;; *) continue ;; esac
		# dbus-daemon runs for every user; only the greeter's (uid 42) matters.
		if [[ "$comm" == dbus-daemon ]] && ! grep -q '^Uid:[[:space:]]*42[[:space:]]' "$dir/status" 2>/dev/null; then
			continue
		fi
		key="${dir##*/}:${comm}"
		[[ -n "${SEEN[$key]:-}" ]] && continue
		SEEN[$key]=1
		found=1
		print_process_environment "$dir"
	done
	return $((1 - found))
}

report_greeter_processes() {
	section "greeter process environment (first sight of each pid)"
	local seen_any=0
	if [[ "$MODE" == sample && "$SAMPLES" -gt 0 ]]; then
		# A crashing greeter lives about a second and is replaced at once, so
		# one look rarely catches it. Poll by count, not by clock.
		for _ in $(seq 1 "$SAMPLES"); do
			scan_greeter_processes && seen_any=1
			sleep 0.25
		done
	else
		scan_greeter_processes && seen_any=1
	fi
	[[ "$seen_any" == 1 ]] || echo "(no greeter process was running)"
}

report_coredumps() {
	section "gnome-shell core dumps"
	if command -v coredumpctl >/dev/null 2>&1; then
		coredumpctl list --no-pager 2>&1 | tail -n 30 || true
		# `coredumpctl info` carries the whole stack trace the gate's journal
		# filter used to cut down to the lines that matched `mutter`.
		coredumpctl info --no-pager -1 /usr/bin/gnome-shell 2>&1 | head -n 200 || true
	fi
	section "environment systemd-coredump recorded for the last gnome-shell crash"
	# fc2e22bc...: the MESSAGE_ID systemd-coredump logs every dump under.
	journalctl -b --no-pager -o json -n 1 \
		MESSAGE_ID=fc2e22bc6ee647b6b90729ab34a250b1 COREDUMP_EXE=/usr/bin/gnome-shell 2>/dev/null |
		ENV_RE="$ENV_RE" python3 -c '
import json, os, re, sys
rx = re.compile(os.environ["ENV_RE"])
found = False
for line in sys.stdin:
    entry = json.loads(line)
    found = True
    for key in ("COREDUMP_PID", "COREDUMP_UNIT", "COREDUMP_SESSION", "COREDUMP_CGROUP", "COREDUMP_SIGNAL_NAME", "COREDUMP_CMDLINE"):
        value = entry.get(key)
        if isinstance(value, list):
            value = bytes(value).decode("utf-8", "replace")
        print(f"{key}={value}")
    environ = entry.get("COREDUMP_ENVIRON")
    if isinstance(environ, list):
        environ = bytes(environ).decode("utf-8", "replace")
    if environ is None:
        print("COREDUMP_ENVIRON is not in this journal entry")
    else:
        lines = [part for part in re.split(r"[\n\0]", environ) if rx.match(part)]
        print("COREDUMP_ENVIRON renderer and session variables:")
        print("\n".join(lines) if lines else "(none)")
if not found:
    print("(no gnome-shell core dump in this boot)")
' 2>&1 || echo "(could not read the journal entry)"
}

main() {
	echo "greeter graphics evidence, mode=${MODE} samples=${SAMPLES}"
	report_identity
	report_drm
	report_software_gl
	report_managers
	report_greeter_processes
	report_coredumps
}

# The gate pipes this file into `bash -s`, which reads the script from stdin as
# it runs. Give every command inside main /dev/null so none can swallow the rest
# of the script.
main </dev/null
exit 0
