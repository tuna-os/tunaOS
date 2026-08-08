#!/usr/bin/env bats
# poweroff_and_wait_vm must not return while the install VM is still alive.
#
# Both callers boot the installed disk immediately afterwards on the SAME
# `-pidfile`, and QEMU holds an exclusive lock on that file for its whole life.
# So a guest that overstays its poweroff does not delay the next boot, it
# forbids it:
#
#   qemu-system-x86_64: cannot create PID file: Cannot lock pid file:
#   Resource temporarily unavailable
#
# That is run 31140233496 (albacore:cosmic): the install had already logged
# "Installation complete!", the old 70s window expired on a guest whose
# `cryptsetup luksClose` had just reported the root mapping still in use, and
# the cell died on the passphrase gate's launch with no ERROR line of its own.
#
# These tests drive the real function out of iso-e2e.sh with a stub guest, so
# they measure behaviour rather than the presence of a keyword.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/iso-e2e.sh"

setup() {
	PIDFILE="$BATS_TEST_TMPDIR/qemu.pid"
	MONSOCK="$BATS_TEST_TMPDIR/monitor.sock"
	SSH_LOG="$BATS_TEST_TMPDIR/ssh.log"
	SOCAT_LOG="$BATS_TEST_TMPDIR/socat.log"
	BIN="$BATS_TEST_TMPDIR/bin"
	mkdir -p "$BIN"

	# The driver evaluates the shipped function and its helper, then runs it
	# against whatever the test has staged. `sleep` becomes a token delay so a
	# 180-iteration poll finishes in milliseconds without turning the polls
	# into a busy race.
	cat >"$BATS_TEST_TMPDIR/drive.sh" <<-'EOF'
		set -Eeuo pipefail
		SCRIPT="$1"
		eval "$(grep '^POWEROFF_WAIT_SECS=' "$SCRIPT")"
		eval "$(sed -n '/^wait_pid_gone()/,/^}/p' "$SCRIPT")"
		eval "$(sed -n '/^poweroff_and_wait_vm()/,/^}/p' "$SCRIPT")"
		GUEST_SSH=("$SSH_STUB")
		sleep() { command sleep 0.02; }
		if [[ -n "${STUB_KILL_NOOP:-}" ]]; then
			# A guest that cannot be signalled away, i.e. every kill "works"
			# and nothing ever dies.
			kill() { return 0; }
		fi
		rc=0
		poweroff_and_wait_vm || rc=$?
		echo "rc=${rc}"
		exit "$rc"
	EOF
}

teardown() {
	[[ -n "${VMPID:-}" ]] && kill -KILL "$VMPID" 2>/dev/null
	return 0
}

# A stand-in for the daemonized QEMU: orphaned on purpose, so that killing it
# does not leave a zombie that `kill -0` would still report as alive.
spawn_fake_vm() {
	VMPID="$(bash -c 'sleep 300 >/dev/null 2>&1 & printf "%s\n" "$!"')"
	printf '%s\n' "$VMPID" >"$PIDFILE"
}

# The guest obeys, but takes its time about it — the case the wait loop exists
# for. The delay is long enough that the poll below has to run.
stub_ssh_that_powers_off() {
	cat >"$BIN/ssh-obeys" <<-EOF
		#!/usr/bin/env bash
		printf '%s\n' "\$*" >>"$SSH_LOG"
		( command sleep 0.5; kill -TERM "\$(cat "$PIDFILE")" 2>/dev/null ) >/dev/null 2>&1 &
		exit 0
	EOF
	chmod +x "$BIN/ssh-obeys"
	printf '%s\n' "$BIN/ssh-obeys"
}

# The guest wedges: poweroff is accepted and nothing happens.
stub_ssh_that_ignores() {
	cat >"$BIN/ssh-ignores" <<-EOF
		#!/usr/bin/env bash
		printf '%s\n' "\$*" >>"$SSH_LOG"
		exit 0
	EOF
	chmod +x "$BIN/ssh-ignores"
	printf '%s\n' "$BIN/ssh-ignores"
}

drive() {
	run env \
		SSH_STUB="$1" \
		QEMU_PIDFILE="$PIDFILE" \
		MONITOR_SOCK="${MONITOR_SOCK_OVERRIDE:-$MONSOCK}" \
		PATH="$BIN:$PATH" \
		bash "$BATS_TEST_TMPDIR/drive.sh" "$SCRIPT"
}

@test "a guest that powers itself off is waited for, not forced" {
	spawn_fake_vm
	# 60 polls of the token sleep, i.e. well past the stub's 0.5s.
	TUNAOS_E2E_POWEROFF_WAIT=60
	export TUNAOS_E2E_POWEROFF_WAIT
	drive "$(stub_ssh_that_powers_off)"
	[ "$status" -eq 0 ]
	[[ "$output" == *"Waiting for VM to shut down"* ]]
	# The whole point of the ladder is that it stays out of the way here.
	[[ "$output" != *"forcing it down"* ]]
	grep -q 'systemctl poweroff' "$SSH_LOG"
	run kill -0 "$VMPID"
	[ "$status" -ne 0 ]
}

# The regression. Before this, the function returned with the VM still running
# and the caller walked straight into the pidfile lock.
@test "a wedged guest is killed, so the pidfile lock is free for the next boot" {
	spawn_fake_vm
	MONITOR_SOCK_OVERRIDE="$BATS_TEST_TMPDIR/no-such.sock"
	TUNAOS_E2E_POWEROFF_WAIT=2
	export TUNAOS_E2E_POWEROFF_WAIT
	drive "$(stub_ssh_that_ignores)"
	[ "$status" -eq 0 ]
	[[ "$output" == *"did not power off within 2s"* ]]
	run kill -0 "$VMPID"
	[ "$status" -ne 0 ]
	# QEMU unlinks its own pidfile and did not get to; a dead pid left here
	# would have cleanup_vm signalling whatever recycles the number.
	[ ! -e "$PIDFILE" ]
}

@test "the wait window is a tunable, not a hardcoded 70 seconds" {
	# 70s (30 x 2s) could not outlast systemd's own 90s stop timeout, let alone
	# the dm-detach retries after it.
	run grep -c 'TUNAOS_E2E_POWEROFF_WAIT' "$SCRIPT"
	[ "$output" -ge 1 ]
	default="$(unset TUNAOS_E2E_POWEROFF_WAIT; eval "$(grep '^POWEROFF_WAIT_SECS=' "$SCRIPT")"; echo "$POWEROFF_WAIT_SECS")"
	[ "$default" -ge 120 ]
}

@test "escalation asks over ACPI before it signals the process" {
	spawn_fake_vm
	# A real socket file, because the code requires one before it tries.
	python3 - "$MONSOCK" <<-'PY'
		import socket, sys
		s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		s.bind(sys.argv[1])
		s.listen(1)
	PY
	cat >"$BIN/socat" <<-EOF
		#!/usr/bin/env bash
		cat >>"$SOCAT_LOG"
		kill -TERM "\$(cat "$PIDFILE")" 2>/dev/null || true
	EOF
	chmod +x "$BIN/socat"
	TUNAOS_E2E_POWEROFF_WAIT=2
	export TUNAOS_E2E_POWEROFF_WAIT
	drive "$(stub_ssh_that_ignores)"
	[ "$status" -eq 0 ]
	grep -q 'system_powerdown' "$SOCAT_LOG"
	run kill -0 "$VMPID"
	[ "$status" -ne 0 ]
}

@test "a VM that survives SIGKILL fails loudly instead of returning quietly" {
	spawn_fake_vm
	MONITOR_SOCK_OVERRIDE="$BATS_TEST_TMPDIR/no-such.sock"
	TUNAOS_E2E_POWEROFF_WAIT=1
	STUB_KILL_NOOP=1
	export TUNAOS_E2E_POWEROFF_WAIT STUB_KILL_NOOP
	drive "$(stub_ssh_that_ignores)"
	[ "$status" -ne 0 ]
	[[ "$output" == *"survived SIGKILL"* ]]
	# Still the only record of which process to chase.
	[ -e "$PIDFILE" ]
}

@test "an ssh poweroff that fails is reported, not swallowed" {
	# Whether the guest was even asked changes what a long wait means.
	cat >"$BIN/ssh-broken" <<-'EOF'
		#!/usr/bin/env bash
		exit 255
	EOF
	chmod +x "$BIN/ssh-broken"
	rm -f "$PIDFILE"
	TUNAOS_E2E_POWEROFF_WAIT=1
	export TUNAOS_E2E_POWEROFF_WAIT
	drive "$BIN/ssh-broken"
	[ "$status" -eq 0 ]
	[[ "$output" == *"did not return cleanly"* ]]
}

@test "the passphrase gate names a QEMU launch it could not make" {
	# The reported run's only clue was qemu's own one-liner and "exit code 1".
	blk="$(sed -n '/LUKS passphrase gate: booting/,/luks-first-boot.py/p' "$SCRIPT")"
	[ -n "$blk" ]
	grep -qF 'tunaos-iso-e2e-installed' <<<"$blk"
	grep -q 'ERROR: QEMU would not start' <<<"$blk"
	grep -qi 'lock pid file' <<<"$blk"
}
