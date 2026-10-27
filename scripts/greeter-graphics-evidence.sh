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
	systemctl show-environment 2>&1 | grep -E "$ENV_RE" || true
	section "user managers and sessions"
	systemctl list-units --all --no-pager --no-legend 'user@*' 'user-runtime-dir@*' 2>&1 || true
	loginctl list-sessions --no-legend 2>&1 || true
}

# Resolve membership on each poll: sessions and workers can disappear/restart.
# Names alone cannot distinguish a user's desktop from the GDM greeter.
greeter_process_records() {
	PROC="$PROC" PROCESSES="$PROCESSES" ENV_RE="$ENV_RE" python3 -c '
import base64, os, pathlib, re, subprocess, time

proc = pathlib.Path(os.environ["PROC"])
names = set(os.environ["PROCESSES"].split())
workers = {"gdm-session-wor", "gdm-wayland-ses"}
# User services leave the login scope. Admit only these explicit GDM units.
user_units = {"gnome-shell": {"org.gnome.Shell@gdm.service"},
              "dbus-daemon": {"dbus.service"}}
deadline = time.monotonic() + 0.25
rx = re.compile(os.environ["ENV_RE"])


def loginctl(*args):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired("loginctl", 0.25)
    result = subprocess.run(["loginctl", *args], capture_output=True, text=True, timeout=remaining)
    if result.returncode:
        raise ValueError("session query failed")
    return result.stdout

try:
    sessions = loginctl("list-sessions", "--no-legend").splitlines()
except (OSError, ValueError, subprocess.TimeoutExpired):
    sessions = []
scopes = {}
for row in sessions:
    if time.monotonic() >= deadline:
        break
    fields = row.split()
    if not fields or not re.fullmatch(r"[A-Za-z0-9_-]+", fields[0]):
        continue
    try:
        properties = dict(line.split("=", 1) for line in loginctl(
            "show-session", fields[0], "-p", "Class", "-p", "Service",
            "-p", "Seat", "-p", "User", "-p", "Scope").splitlines() if "=" in line)
        scope = properties.get("Scope", "")
        uid = int(properties.get("User", ""))
        if (properties.get("Class") == "greeter"
                and properties.get("Service") == "gdm-launch-environment"
                and properties.get("Seat") == "seat0" and uid > 0
                and re.fullmatch(r"session-[A-Za-z0-9_-]+\.scope", scope)):
            scopes[scope] = uid
    except (OSError, ValueError, subprocess.TimeoutExpired):
        continue

def read_at(fd, name):
    with os.fdopen(os.open(name, os.O_RDONLY, dir_fd=fd), "rb") as stream:
        return stream.read()

def identity(fd):
    comm = read_at(fd, "comm").decode().strip()
    status = dict(line.split(":", 1) for line in read_at(fd, "status").decode().splitlines() if ":" in line)
    uids = tuple(int(value) for value in status["Uid"].split())
    if len(uids) != 4 or len(set(uids)) != 1:
        raise ValueError("credentials changed")
    parent = int(status["PPid"])
    # Field 22 follows the final parenthesis around comm in /proc/PID/stat.
    started = read_at(fd, "stat").decode().rsplit(")", 1)[1].split()[19]
    groups = frozenset(part for line in read_at(fd, "cgroup").decode().splitlines()
                       for part in line.split(":", 2)[-1].split("/"))
    return comm, uids[0], parent, groups, started

candidates = {}
handles = {}
for path in proc.glob("[0-9]*"):
    fd = None
    try:
        # Holding this directory ties later reads to this process, not to a
        # replacement process that reuses its numeric PID.
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        if read_at(fd, "comm").decode().strip() not in names:
            continue
        record = identity(fd)
        pid = int(path.name)
        candidates[pid] = record
        handles[pid] = fd
        fd = None
    except (OSError, ValueError, KeyError, IndexError):
        continue
    finally:
        if fd is not None:
            os.close(fd)

selected = set()
for pid, (comm, uid, parent, groups, started) in candidates.items():
    # Root is admitted only for GDM workers in a verified greeter scope.
    if any(scope in groups and (uid == owner or (uid == 0 and comm in workers))
           for scope, owner in scopes.items()):
        selected.add(pid)
    elif (uid in scopes.values() and f"user@{uid}.service" in groups
          and groups.intersection(user_units.get(comm, set()))):
        selected.add(pid)

# A root worker may still be in gdm.service. Retain it only when it is
# an ancestor in the known process chain of a verified greeter member.
for pid in list(selected):
    owner = candidates[pid][1]
    visited = {pid}
    parent = candidates[pid][2]
    while parent in candidates and parent not in visited:
        visited.add(parent)
        comm, uid, next_parent, groups, started = candidates[parent]
        if uid == 0 and comm in workers:
            selected.add(parent)
        elif uid != owner or uid == 0:
            break
        parent = next_parent
for pid in sorted(selected):
    fd = handles[pid]
    try:
        record = candidates[pid]
        if identity(fd) != record:
            continue
        environ = read_at(fd, "environ").decode("utf-8", "replace")
        if identity(fd) != record:
            continue
        comm, uid, parent, groups, started = record
        lines = [line for line in environ.replace("\0", "\n").splitlines() if rx.match(line)]
        report = f"--- pid {pid} comm={comm} uid={uid}\n"
        report += "\n".join(lines) if lines else "(no renderer or session variables)"
        payload = base64.b64encode((report + "\n").encode()).decode()
        print(f"{pid}:{started}:{comm} {payload}")
    except (OSError, ValueError, KeyError, IndexError):
        continue
for fd in handles.values():
    os.close(fd)
' 2>/dev/null || true
}

# scan_greeter_processes — print each verified greeter-chain process once.
declare -A SEEN=()
scan_greeter_processes() {
	local key payload found=0
	while read -r key payload; do
		[[ -n "$key" && -n "$payload" ]] || continue
		[[ -n "${SEEN[$key]:-}" ]] && continue
		SEEN[$key]=1
		found=1
		printf '%s' "$payload" | base64 --decode
	done < <(greeter_process_records)
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
	[[ "$seen_any" == 1 ]] || echo "(no verified greeter process was found)"
}

report_coredumps() {
	section "gnome-shell core dumps"
	if command -v coredumpctl >/dev/null 2>&1; then
		coredumpctl list --no-pager 2>&1 | tail -n 30 || true
		# `coredumpctl info` carries the whole stack trace the gate's journal
		# filter used to cut down to the lines that matched `mutter`.
		coredumpctl info --no-pager -1 /usr/bin/gnome-shell 2>&1 || true
	fi
	section "environment systemd-coredump recorded for the last gnome-shell crash"
	# fc2e22bc...: the MESSAGE_ID systemd-coredump logs every dump under.
	journalctl -b --all --no-pager -o json -n 1 \
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
