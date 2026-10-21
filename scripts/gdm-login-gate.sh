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

guest bash -s -- "$TEST_USER" <<'CHECK_GREETER'
set -euo pipefail
user="$1"
systemctl is-active --quiet display-manager.service
if loginctl list-sessions --no-legend | awk -v user="$user" '$3 == user { found=1 } END { exit !found }'; then
	echo "test account already has a session before keyboard input" >&2
	exit 1
fi
CHECK_GREETER
"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-greeter.png" --require-paint

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
sleep 3
"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-logged-in.png" --require-paint

# Slow software-rendered shells may not have their lock path ready when the
# first request lands; re-issue it until the hint flips.
locked=0
for round in 1 2 3; do
	echo "==> lock attempt $round/3 for session $session_id"
	# Do not fail fast here: a session that died right after login must
	# reach the polling loop and the diagnostics branch, not die silently.
	guest loginctl lock-session "$session_id" || true
	for _ in $(seq 1 20); do
		if [[ "$(guest loginctl show-session "$session_id" -p LockedHint --value 2>/dev/null || true)" == yes ]]; then
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
	if [[ "$(guest loginctl show-session "$session_id" -p LockedHint --value 2>/dev/null || true)" == no ]]; then
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
