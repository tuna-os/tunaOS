#!/usr/bin/env bash
# Verify a real GDM login and lock/unlock on an already-booted Corral VM.
set -euo pipefail

NAME="${1:?usage: $0 <vm-name> <output-dir> <test-user>}"
OUT="${2:?usage: $0 <vm-name> <output-dir> <test-user>}"
TEST_USER="${3:?usage: $0 <vm-name> <output-dir> <test-user>}"
TEST_PASSWORD="${TUNAOS_GDM_TEST_PASSWORD:?test password must be set in the environment}"
CORRAL="${CORRAL:-corral}"
RESULT="${OUT}/corral/result.json"

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
echo "==> loginctl sessions"
loginctl list-sessions --no-legend || true
if [[ -n "$session" ]]; then
	echo "==> session $session"
	loginctl show-session "$session" -p Name -p Type -p Seat -p Active -p State -p Service -p LockedHint -p IdleHint || true
	uid="$(id -u "$user" 2>/dev/null || true)"
	if [[ -n "$uid" && -d "/run/user/$uid" ]]; then
		echo "==> user manager state for $user (uid $uid)"
		sudo -u "#$uid" XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user is-system-running 2>&1 || true
		sudo -u "#$uid" XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user list-units --type=target --no-legend 2>&1 | head -n 20 || true
		echo "==> failed user units for $user (uid $uid)"
		sudo -u "#$uid" XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user list-units --state=failed --no-legend 2>&1 | head -n 20 || true
fi
else
	while read -r id _ name _; do
		[[ "$name" == "$user" ]] || continue
		echo "==> session $id"
		loginctl show-session "$id" -p Name -p Type -p Seat -p Active -p State -p Service -p LockedHint -p IdleHint || true
	done < <(loginctl list-sessions --no-legend)
fi
echo "==> AccountsService selection for $user"
cat "/var/lib/AccountsService/users/$user" 2>/dev/null || echo "(no AccountsService file)"
_diag_uid="$(id -u "$user" 2>/dev/null || true)"
if [[ -n "$_diag_uid" ]]; then
	busctl get-property org.freedesktop.Accounts "/org/freedesktop/Accounts/User${_diag_uid}" org.freedesktop.Accounts.User Session 2>&1 || true
fi
echo "==> ScreenSaver state for $user"
if [[ -n "$_diag_uid" ]]; then
	busctl --machine="${user}@.host" --user call org.gnome.ScreenSaver /org/gnome/ScreenSaver org.gnome.ScreenSaver GetActive 2>&1 || true
fi
echo "==> session definitions GDM can choose from"
ls -l /usr/share/wayland-sessions /usr/share/xsessions 2>&1 || true
cat /etc/gdm3/custom.conf /etc/gdm/custom.conf 2>/dev/null || true
echo "==> session directories compiled into GDM"
grep -a -o '/usr/share/[A-Za-z0-9/_-]*sessions[A-Za-z0-9/_-]*' /usr/sbin/gdm3 /usr/sbin/gdm /usr/libexec/gdm-* 2>/dev/null | sort -u || true
echo "==> GDM service"
systemctl status gdm.service --no-pager || true
echo "==> recent greeter, shell, lock and PAM journal (guest SSH sessions excluded)"
journalctl -b --no-pager | grep -Ei 'gdm|gnome-shell|gnome-session|mutter|LockHint|lock-screen|pam.*(fail|authentication)|session opened|session closed' | grep -Ev 'sshd-session|sshd\[' | tail -n 200 || true
GDM_DIAGNOSTICS
}

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
wait_for_paint "${OUT}/gdm-greeter.png" 30

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
		"b true"*) echo yes; return ;;
		"b false"*) echo no; return ;;
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
	2) "$CORRAL" key "$NAME" tab; sleep 1; "$CORRAL" key "$NAME" ret ;;
	3) "$CORRAL" type "$NAME" "$TEST_USER"; sleep 1; "$CORRAL" key "$NAME" ret ;;
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
