#!/usr/bin/env bash
# Verify a real GDM login and lock/unlock on an already-booted Corral VM.
set -euo pipefail

NAME="${1:?usage: $0 <vm-name> <output-dir> <test-user>}"
OUT="${2:?usage: $0 <vm-name> <output-dir> <test-user>}"
TEST_USER="${3:?usage: $0 <vm-name> <output-dir> <test-user>}"
TEST_PASSWORD="${TUNAOS_GDM_TEST_PASSWORD:?test password must be set in the environment}"
CORRAL="${CORRAL:-corral}"
RESULT="${OUT}/corral/result.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVIDENCE_SCRIPT="${SCRIPT_DIR}/greeter-graphics-evidence.sh"

SSH_HOST="$(jq -er '.ssh.host | select(length > 0)' "$RESULT")"
SSH_PORT="$(jq -er '.ssh.port | select(. > 0)' "$RESULT")"
SSH_USER="$(jq -er '.ssh.user | select(length > 0)' "$RESULT")"
SSH_IDENTITY="$(jq -er '.ssh.identityFile | select(length > 0)' "$RESULT")"
[[ "$SSH_USER" == root ]] || {
	echo "Corral SSH account is not root: ${SSH_USER}" >&2
	exit 1
}

SSH_OPTS=(-F /dev/null -i "$SSH_IDENTITY" -p "$SSH_PORT" -o BatchMode=yes
	-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5)
guest() {
	# Only fixed commands and the validated test-user/session id reach the guest shell.
	# shellcheck disable=SC2029
	ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" "$@"
}

collect_greeter_evidence() {
	# $1 = once|sample, $2 = polls, $3 = artifact name (tunaOS#3969). Evidence
	# only: nothing in here may change the verdict, so it never fails the gate.
	guest bash -s -- "$1" "$2" <"$EVIDENCE_SCRIPT" >"${OUT}/$3" 2>&1 || true
}

collect_egldevice_reproducer() {
	local binary="${TUNAOS_EGL_REPRO_BIN:-}" remote="/run/tunaos-egldevice-reproducer"
	[[ -n "$binary" ]] || return 0
	if [[ ! -f "$binary" ]]; then
		printf 'status=not-run reason=host-reproducer-not-built\n' >"${OUT}/egl-device-reproducer.txt"
		return 0
	fi
	if ! cat "$binary" | guest tee "$remote" >/dev/null; then
		printf 'status=not-run reason=failed-to-stage-probe\n' >"${OUT}/egl-device-reproducer.txt"
		return 0
	fi
	guest chmod 0755 "$remote" || {
		printf 'status=not-run reason=failed-to-mark-probe-executable\n' >"${OUT}/egl-device-reproducer.txt"
		return 0
	}
	guest bash -s -- "$remote" /dev/dri /sys >"${OUT}/egl-device-reproducer.txt" 2>&1 <<'EGL_DEVICE_REPRO' || true
set -u
binary="$1"
dri_dir="$2"
sysfs_root="$3"
device=""
for node in "$dri_dir"/card[0-9]*; do
	[[ -c "$node" ]] || continue
	name="${node##*/}"
	device_sysfs="${sysfs_root}/class/drm/${name}/device"
	driver_path="$(readlink -f "${device_sysfs}/driver" 2>/dev/null || true)"
	driver="${driver_path##*/}"
	vendor="$(cat "${device_sysfs}/vendor" 2>/dev/null || true)"
	device_id="$(cat "${device_sysfs}/device" 2>/dev/null || true)"
	echo "drm_node=${node} driver=${driver:-unknown} vendor=${vendor:-unknown} device=${device_id:-unknown}"
	# QEMU's virtio-vga node uses the PCI bus driver, not a driver named virtio_gpu.
	if [[ "$driver" == virtio_gpu ]] ||
		[[ "$driver" == virtio-pci && "$vendor" == 0x1af4 && "$device_id" == 0x1050 ]]; then
		device="$node"
	fi
done
if [[ -z "$device" ]]; then
	echo 'status=not-run reason=no-virtio-gpu-primary-node'
	exit 0
fi
echo "selected_device=${device}"
echo "kernel=$(uname -r)"
rpm -q mesa-libEGL libglvnd mutter gnome-shell 2>&1 || true
if ! systemctl stop gdm.service; then
	echo 'status=not-run reason=could-not-stop-gdm-for-drm-master'
	exit 0
fi
trap 'systemctl start gdm.service >/dev/null 2>&1 || true' EXIT
ulimit -c 0
	run_case() {
		label="$1"
		shift
		started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		set +e
		timeout --kill-after=5 20 "$@" "$binary" "$device"
		rc=$?
		set -e
		printf 'case=%s exit=%s\n' "$label" "$rc"
		journalctl -k -b --since="$started" --no-pager 2>/dev/null |
			grep -Ei 'segfault|repro-egldevice-swrast|libgallium' || true
	}
echo '=== controls: same image, DRM node, and EGLDevice display attributes ==='
run_case clean env -u LIBGL_ALWAYS_SOFTWARE -u MESA_LOADER_DRIVER_OVERRIDE
run_case software env -u MESA_LOADER_DRIVER_OVERRIDE LIBGL_ALWAYS_SOFTWARE=1
run_case override env -u LIBGL_ALWAYS_SOFTWARE MESA_LOADER_DRIVER_OVERRIDE=swrast
run_case combined env LIBGL_ALWAYS_SOFTWARE=1 MESA_LOADER_DRIVER_OVERRIDE=swrast
EGL_DEVICE_REPRO
}

wait_for_paint() {
	# GDM can take minutes to first-paint on software rendering, and a
	# restarted greeter always starts blank. Poll for a painted frame
	# instead of failing on the first blank one.
	local file="$1" tries="${2:-30}" i=1 line
	while [[ "$i" -le "$tries" ]]; do
		if line="$("$CORRAL" screenshot "$NAME" -o "$file" 2>&1)"; then
			echo "$line"
			case "$line" in
			*"— painted"*) return 0 ;;
			esac
		else
			echo "$line"
		fi
		sleep 10
		i=$((i + 1))
	done
	echo "no painted frame appeared in $file after $tries tries" >&2
	return 1
}
guest_gdm_diagnostics() {
	# $1 = test user, $2 = session id when one is known.
	guest bash -s -- "$1" "${2:-}" <<'GDM_DIAGNOSTICS'
set -u
user="$1"
session="${2:-}"
# Capture the pre-probe state once. A user-bus proxy can create a user manager,
# so neither a supplied session id nor a runtime directory proves a desktop.
echo "==> loginctl sessions (before user-bus diagnostics)"
session_snapshot="$(loginctl list-sessions --no-legend 2>/dev/null || true)"
printf '%s\n' "$session_snapshot"
diagnostic_session=""
while read -r id _ name _; do
	[[ "$name" == "$user" ]] || continue
	properties="$(loginctl show-session "$id" -p Name -p Type -p Seat -p Active -p State -p Service -p LockedHint -p IdleHint 2>/dev/null)" || continue
	echo "==> session $id (snapshot)"
	printf '%s\n' "$properties"
	if [[ -z "$diagnostic_session" && ( -z "$session" || "$session" == "$id" ) ]] &&
		grep -Fqx "Name=$user" <<<"$properties" &&
		grep -qx 'Type=wayland' <<<"$properties" &&
		grep -qx 'Seat=seat0' <<<"$properties" &&
		grep -qx 'Active=yes' <<<"$properties"; then
		diagnostic_session="$id"
	fi
done <<<"$session_snapshot"
uid="$(id -u "$user" 2>/dev/null || true)"
user_manager_active=0
if [[ -n "$diagnostic_session" && "$uid" =~ ^[0-9]+$ ]] &&
	systemctl is-active --quiet "user@${uid}.service"; then
	user_manager_active=1
fi
if [[ -n "$diagnostic_session" && "$uid" =~ ^[0-9]+$ ]]; then
	echo "==> user manager state for $user (uid $uid)"
	# Query PID 1 directly. Do not open a PAM session through sudo/runuser.
	systemctl show "user@${uid}.service" -p ActiveState -p SubState -p Result --no-pager 2>&1 || true
fi
echo "==> AccountsService selection for $user"
cat "/var/lib/AccountsService/users/$user" 2>/dev/null || echo "(no AccountsService file)"
_diag_uid="$(id -u "$user" 2>/dev/null || true)"
if [[ -n "$_diag_uid" ]]; then
	busctl --auto-start=no get-property org.freedesktop.Accounts "/org/freedesktop/Accounts/User${_diag_uid}" org.freedesktop.Accounts.User Session 2>&1 || true
fi
echo "==> ScreenSaver state for $user"
if [[ "$user_manager_active" == 1 && -S "/run/user/$uid/bus" ]]; then
	# --address connects directly to this Unix socket; no machine proxy or PAM
	# helper can recreate a departed user manager. Disable destination-service
	# activation and never fall back if the socket vanishes or access is denied.
	busctl --address="unix:path=/run/user/$uid/bus" --auto-start=no --timeout=5s \
		call org.gnome.ScreenSaver /org/gnome/ScreenSaver org.gnome.ScreenSaver GetActive 2>&1 || true
else
	echo "(skipped: no existing active Wayland session on seat0 with an active user manager and bus socket)"
fi
echo "==> session definitions GDM can choose from"
ls -l /usr/share/wayland-sessions /usr/share/xsessions 2>&1 || true
cat /etc/gdm3/custom.conf /etc/gdm/custom.conf 2>/dev/null || true
echo "==> session directories compiled into GDM"
grep -a -o '/usr/share/[A-Za-z0-9/_-]*sessions[A-Za-z0-9/_-]*' /usr/sbin/gdm3 /usr/sbin/gdm /usr/libexec/gdm-* 2>/dev/null | sort -u || true
echo "==> GDM service"
systemctl status gdm.service --no-pager || true
# Keep authentication chronology separate from noisy input-method errors.
# Emit fixed event labels and numeric metadata, never free-form log messages
# that might contain typed text, passwords or tokens.
journal_summary() {
	local kind="$1" limit="$2" pattern="$3"
	journalctl -b --all --no-pager -o json -n "$limit" --grep="$pattern" 2>/dev/null |
		python3 -c '
import collections, json, re, sys
kind, limit = sys.argv[1], int(sys.argv[2])
events = collections.deque(maxlen=limit)
for line in sys.stdin:
    try:
        entry = json.loads(line)
        message = entry.get("MESSAGE", "")
        if not isinstance(message, str):
            continue
        text = message.lower()
        if kind == "ibus":
            if "ibus" not in text:
                continue
            event = "IBus diagnostic"
        else:
            if "ibus" in text or "sshd" in text or "ssh" in str(entry.get("SYSLOG_IDENTIFIER", "")).lower():
                continue
            if not re.search(r"gdm|pam|session opened|session closed", text):
                continue
            event = "GDM/PAM diagnostic"
            for phrase in ("authentication failure", "authentication failed", "session opened", "session closed"):
                if phrase in text:
                    event = phrase
                    break
        def number(key):
            value = entry.get(key, "")
            return value if isinstance(value, str) and value.isdecimal() else "unknown"
        events.append("time_us=" + number("__REALTIME_TIMESTAMP") + " pid=" + number("_PID") + " event=" + event)
    except (ValueError, TypeError, AttributeError):
        continue
print("\n".join(events) if events else "(no matching events)")
' "$kind" "$limit" || true
}
echo "==> GDM/PAM chronology (up to 200 events; message text omitted)"
journal_summary auth 200 '(?i)^(?!.*(?:ibus|sshd)).*(gdm|pam|session opened|session closed)'
echo "==> IBus diagnostics (up to 50 events; message text omitted)"
journal_summary ibus 50 '(?i)ibus'

GDM_DIAGNOSTICS
}

collect_failure_on_exit() {
	local status=$?
	trap - EXIT
	if [[ "$status" -ne 0 ]]; then
		# Required screenshots can exit under errexit before diagnostics run.
		# Centralize collection here so explicit failures also collect only once.
		collect_greeter_evidence once 0 greeter-graphics-evidence-after-failure.txt || true
	fi
	exit "$status"
}
trap collect_failure_on_exit EXIT

echo "==> waiting for Corral SSH to inspect the GDM greeter"
for _ in $(seq 1 60); do
	if guest true >/dev/null 2>&1; then
		break
	fi
	sleep 2
done
guest true || {
	echo "GDM login gate could not reach the guest over SSH" >&2
	exit 1
}

# Pin the session GDM starts: a fresh image has no per-user history, so
# without this GDM falls back to its own default (currently the GNOME
# session, which is broken on newer GNOME) instead of Tuna. The greeter
# only picks this up on startup, so restart it after writing the selection.
guest_accts_dir="${TUNAOS_GDM_ACCOUNTS_DIR:-/var/lib/AccountsService/users}"
guest mkdir -p "$guest_accts_dir"
printf '[User]\nSession=tuna\nXSession=tuna\n' | guest tee "$guest_accts_dir/$TEST_USER" >/dev/null
# AccountsService caches each user's Session after its first read; Ubuntu's
# daemon keeps serving the empty value it loaded before this file existed (the
# bus property reads ""), so GDM falls back to GNOME. Restart it so the
# selection above is what GDM reads.
guest systemctl restart accounts-daemon.service || true

# The optional Albacore PR probe temporarily stops GDM, tests the exact EGLDevice
# call under four environment controls, and restarts GDM before this gate resumes.
# It is evidence-only: missing probe tooling/device data never changes the verdict.
collect_egldevice_reproducer
guest systemctl restart gdm.service
for _ in $(seq 1 60); do
	if guest systemctl is-active --quiet display-manager.service; then
		break
	fi
	sleep 2
done
guest systemctl is-active --quiet display-manager.service || {
	echo "GDM did not come back after restart for the Tuna session selection" >&2
	exit 1
}
guest bash -s -- "$TEST_USER" <<'CHECK_GREETER'
set -euo pipefail
user="$1"
if loginctl list-sessions --no-legend | awk -v user="$user" '$3 == user { found=1 } END { exit !found }'; then
	echo "test account already has a session before keyboard input" >&2
	exit 1
fi
CHECK_GREETER
# Record the greeter's graphics inputs while it is (re)starting: its renderer
# environment, the DRM devices, the software-GL decision, any core dump.
# Forty polls at 250 ms intervals; bounded membership queries add time.
# Evidence collection has no effect on what the gate decides.
collect_greeter_evidence sample 40 greeter-graphics-evidence.txt
if ! wait_for_paint "${OUT}/gdm-greeter.png" 30; then
	echo "GDM greeter did not paint; collecting after-failure diagnostics" >&2
	guest_gdm_diagnostics "$TEST_USER" || true
	exit 1
fi

# Corral creates exactly one regular, non-sudo user in a disposable image
# layer. Slower greeters may still be assigning keyboard focus when the first
# frame paints, so settle before sending any keys. GDM versions also differ in
# what opens the tile (pre-focused Enter, Tab-then-Enter, or type-ahead
# selection); the attempt loop below tries each in turn.
sleep 3

graphical_session() {
	guest bash -s -- "$TEST_USER" <<'FIND_SESSION'
set -euo pipefail
user="$1"
for session in $(loginctl list-sessions --no-legend | awk -v user="$user" '$3 == user { print $1 }'); do
	properties="$(loginctl show-session "$session" -p Type -p Seat -p Active)"
	if grep -qx 'Type=wayland' <<<"$properties" &&
		grep -qx 'Seat=seat0' <<<"$properties" &&
		grep -qx 'Active=yes' <<<"$properties"; then
		printf '%s\n' "$session"
		exit 0
	fi
done
exit 1
FIND_SESSION
}

# The desktop's lock contract is org.gnome.ScreenSaver on the user's session
# bus: Tuna and GNOME both publish it, and it reports the compositor's
# confirmed lock state. Tuna does not subscribe to logind's Lock signal and
# never sets LockedHint, so those only serve as a fallback.
screensaver_call() {
	# --machine reaches the user's bus through systemd's own proxy. Opening the
	# bus socket directly as the user is refused ("Operation not permitted")
	# from the SSH login context on SELinux images.
	guest busctl --machine="${TEST_USER}@.host" --user call \
		org.gnome.ScreenSaver /org/gnome/ScreenSaver org.gnome.ScreenSaver "$1"
}

# Prints yes, no or unknown. unknown never counts as a confirmation either way.
lock_state() {
	local out hint
	if out="$(screensaver_call GetActive 2>/dev/null)"; then
		case "$out" in
		"b true"*)
			echo yes
			return
			;;
		"b false"*)
			echo no
			return
			;;
		esac
	fi
	hint="$(guest loginctl show-session "$session_id" -p LockedHint --value 2>/dev/null || true)"
	case "$hint" in
	yes | no) echo "$hint" ;;
	*) echo unknown ;;
	esac
}

session_id=""
for attempt in 1 2 3; do
	# Each round starts from the tile list: Esc backs out of any prompt a
	# previous round left open, so attempts cannot poison each other with
	# half-typed input. The sleeps let slow software-rendered greeters
	# finish their transitions before keys land.
	"$CORRAL" key "$NAME" esc
	sleep 2
	case "$attempt" in
	1) "$CORRAL" key "$NAME" ret ;;
	2)
		"$CORRAL" key "$NAME" tab
		sleep 1
		"$CORRAL" key "$NAME" ret
		;;
	3)
		"$CORRAL" type "$NAME" "$TEST_USER"
		sleep 1
		"$CORRAL" key "$NAME" ret
		;;
	esac
	sleep 3
	"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-attempt-${attempt}.png" --require-paint
	sleep 2
	"$CORRAL" type "$NAME" "$TEST_PASSWORD"
	sleep 1
	"$CORRAL" key "$NAME" ret
	for _ in $(seq 1 20); do
		if session_id="$(graphical_session)"; then
			break 2
		fi
		sleep 2
	done
done
[[ -n "$session_id" ]] || {
	echo "GDM did not start an active Wayland session for ${TEST_USER}" >&2
	"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-login-failed.png" --require-paint || true
	guest_gdm_diagnostics "$TEST_USER" || true
	exit 1
}
echo "TUNAOS_GDM_LOGIN_OK user=${TEST_USER} session=${session_id}"
# Record which desktop actually started: the gate must validate the Tuna
# session, not whatever GDM falls back to. The cgroup tree names the session
# leader (tuna-session vs gnome-session). Best effort only.
guest loginctl session-status "$session_id" 2>/dev/null | head -n 25 || true
sleep 3
"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-logged-in.png" --require-paint

# Lock through the desktop's own contract (org.gnome.ScreenSaver), falling back
# to logind. Slow software-rendered shells may not have it ready when the first
# request lands, so re-issue until the lock is confirmed.
locked=0
for round in 1 2 3; do
	echo "==> lock attempt $round/3 for session $session_id"
	# Do not fail fast here: a session that died right after login must
	# reach the polling loop and the diagnostics branch, not die silently.
	screensaver_call Lock >/dev/null 2>&1 || guest loginctl lock-session "$session_id" || true
	for _ in $(seq 1 20); do
		if [[ "$(lock_state)" == yes ]]; then
			locked=1
			break 2
		fi
		sleep 2
	done
	sleep 2
done
[[ "$locked" == 1 ]] || {
	echo "the Tuna desktop did not report its session locked" >&2
	"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-lock-failed.png" --require-paint || true
	guest_gdm_diagnostics "$TEST_USER" "$session_id" || true
	exit 1
}
echo "TUNAOS_GDM_LOCK_OK user=${TEST_USER} session=${session_id}"
# GNOME deactivates outputs on lock in headless VNC, so the locked frame is a
# blank placeholder by design. LockedHint=yes above is the lock proof; keep
# the screenshot as evidence without requiring paint.
"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-locked.png"

# Wake the lock screen, then authenticate through the desktop's PAM path.
# Type and submit separately so a slow shield finishes painting the prompt
# before the password lands and Enter submits it.
"$CORRAL" key "$NAME" ret
sleep 1
"$CORRAL" type "$NAME" "$TEST_PASSWORD"
sleep 1
"$CORRAL" key "$NAME" ret
unlocked=0
for _ in $(seq 1 30); do
	if [[ "$(lock_state)" == no ]]; then
		unlocked=1
		break
	fi
	sleep 2
done
[[ "$unlocked" == 1 ]] || {
	echo "the Tuna desktop did not unlock with the test user's password" >&2
	"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-unlock-failed.png" --require-paint || true
	guest_gdm_diagnostics "$TEST_USER" "$session_id" || true
	exit 1
}
echo "TUNAOS_GDM_UNLOCK_OK user=${TEST_USER} session=${session_id}"
"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-unlocked.png" --require-paint
