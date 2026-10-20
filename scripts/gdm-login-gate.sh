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
# layer, so Enter selects its GDM tile and the password authenticates it.
"$CORRAL" key "$NAME" ret
sleep 2
"$CORRAL" type "$NAME" "$TEST_PASSWORD" --enter

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
for _ in $(seq 1 60); do
	if session_id="$(graphical_session)"; then
		break
	fi
	sleep 2
done
[[ -n "$session_id" ]] || {
	echo "GDM did not start an active Wayland session for ${TEST_USER}" >&2
	exit 1
}
echo "TUNAOS_GDM_LOGIN_OK user=${TEST_USER} session=${session_id}"
"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-logged-in.png" --require-paint

guest loginctl lock-session "$session_id"
locked=0
for _ in $(seq 1 30); do
	if [[ "$(guest loginctl show-session "$session_id" -p LockedHint --value 2>/dev/null || true)" == yes ]]; then
		locked=1
		break
	fi
	sleep 2
done
[[ "$locked" == 1 ]] || {
	echo "the Tuna desktop did not report its session locked" >&2
	exit 1
}
echo "TUNAOS_GDM_LOCK_OK user=${TEST_USER} session=${session_id}"
"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-locked.png" --require-paint

# Wake the lock screen, then authenticate through the desktop's PAM path.
"$CORRAL" key "$NAME" ret
sleep 1
"$CORRAL" type "$NAME" "$TEST_PASSWORD" --enter
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
	exit 1
}
echo "TUNAOS_GDM_UNLOCK_OK user=${TEST_USER} session=${session_id}"
"$CORRAL" screenshot "$NAME" -o "${OUT}/gdm-unlocked.png" --require-paint
