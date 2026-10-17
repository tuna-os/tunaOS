#!/usr/bin/env bats
# Unit tests for scripts/corral-boot-gate.sh — the disk boot gate run by
# Corral. corral, podman (the backend probe) and id are stubbed; the stub
# corral writes the console a guest would have printed.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
GATE_SCRIPT="${REPO_ROOT}/scripts/corral-boot-gate.sh"

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="${TEST_ROOT}/stub-bin"
	mkdir -p "${STUB_BIN}"
	export PATH="${STUB_BIN}:${PATH}"
	export HOME="${TEST_ROOT}/home"
	export CORRAL_LOG="${TEST_ROOT}/corral.log"
	export BASE_CONTRACT_GRACE=2
	unset TUNAOS_QCOW2_FILESYSTEM DISK_CONTRACT

	# The script refuses to run as anyone but root.
	cat >"${STUB_BIN}/id" <<'ID'
#!/usr/bin/env bash
[[ "$1" == -u ]] && { echo 0; exit 0; }
exec /usr/bin/id "$@"
ID

	# probe_image_backend runs the image's own shell through podman.
	cat >"${STUB_BIN}/podman" <<'PODMAN'
#!/usr/bin/env bash
printf 'BACKEND=%s\nSEALED=%s\n' "${PROBE_BACKEND:-ostree}" "${PROBE_SEALED:-0}"
PODMAN

	# vmtest: record the arguments, write the guest console, exit with the
	# verdict the test asks for.
	cat >"${STUB_BIN}/corral" <<'CORRAL'
#!/usr/bin/env bash
echo "corral $*" >>"$CORRAL_LOG"
case "$1" in
vmtest)
	if [[ "$*" == *"--help"* ]]; then
		echo "      --fail-marker string"
		exit 0
	fi
	name=$2
	artifacts=
	prev=
	for arg in "$@"; do
		[[ "$prev" == --artifacts ]] && artifacts=$arg
		prev=$arg
	done
	mkdir -p "$HOME/.local/share/corral/vms/$name" "$artifacts"
	printf '%b' "${GUEST_CONSOLE:-}" >"$HOME/.local/share/corral/vms/$name/serial.log"
	cp "$HOME/.local/share/corral/vms/$name/serial.log" "$artifacts/serial.log"
	touch "$artifacts/ready.png"
	exit "${VMTEST_RC:-0}"
	;;
delete) exit 0 ;;
esac
CORRAL
	chmod +x "${STUB_BIN}"/*
	OUT="${TEST_ROOT}/verify-out"
}

teardown() {
	rm -rf "${TEST_ROOT}"
}

@test "a desktop and base contract pass is a pass" {
	export GUEST_CONSOLE='TUNAOS_BASE_CONTRACT_OK state=running\nTUNAOS_DESKTOP_CONTRACT_OK desktop=gnome\n'
	run bash "$GATE_SCRIPT" ghcr.io/tuna-os/yellowfin:gnome-testing "$OUT" 600
	[ "$status" -eq 0 ]
	grep -q 'TUNAOS_DESKTOP_CONTRACT_OK' "$OUT/serial.log"
	[ -f "$OUT/ready.png" ]
}

@test "the guest opts out of adoption reports from the first boot" {
	export GUEST_CONSOLE='TUNAOS_BASE_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_OK\n'
	run bash "$GATE_SCRIPT" img "$OUT" 600
	[ "$status" -eq 0 ]
	grep -q -- '--karg tunaos.countme=0' "$CORRAL_LOG"
	grep -q -- '--karg systemd.journald.forward_to_console=1' "$CORRAL_LOG"
	grep -q -- '--ready-marker TUNAOS_DESKTOP_CONTRACT_OK' "$CORRAL_LOG"
	grep -q -- '--fail-marker TUNAOS_(DESKTOP|BASE)_CONTRACT_FAIL|' "$CORRAL_LOG"
	grep -q -- '--timeout 600s' "$CORRAL_LOG"
}

@test "a sealed image installs on ext4, an unsealed one on xfs" {
	export GUEST_CONSOLE='TUNAOS_BASE_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_OK\n'
	PROBE_BACKEND=composefs-native PROBE_SEALED=1 run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 0 ]
	grep -q -- '--filesystem ext4' "$CORRAL_LOG"
	: >"$CORRAL_LOG"
	PROBE_BACKEND=ostree PROBE_SEALED=0 run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 0 ]
	grep -q -- '--filesystem xfs' "$CORRAL_LOG"
}

@test "TUNAOS_QCOW2_FILESYSTEM overrides the probed filesystem" {
	export GUEST_CONSOLE='TUNAOS_BASE_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_OK\n'
	TUNAOS_QCOW2_FILESYSTEM=ext4 PROBE_SEALED=0 run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 0 ]
	grep -q -- '--filesystem ext4' "$CORRAL_LOG"
}

@test "a base contract failure after the desktop marker fails the gate (tunaOS#2664)" {
	export GUEST_CONSOLE='TUNAOS_DESKTOP_CONTRACT_OK\nTUNAOS_BASE_CONTRACT_FAIL reason=no_bus\n'
	run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"base contract FAILED"* ]]
}

@test "a missing base marker only warns, as iso-e2e.sh does" {
	export GUEST_CONSOLE='TUNAOS_DESKTOP_CONTRACT_OK\n'
	run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"system bus unverified"* ]]
}

@test "corral's verdict is the gate's exit code, with the console tail" {
	export GUEST_CONSOLE='Entering emergency mode\n'
	VMTEST_RC=6 run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 6 ]
	[[ "$output" == *"serial| Entering emergency mode"* ]]
}

@test "a corral without --fail-marker is refused before any build" {
	cat >"${STUB_BIN}/corral" <<'CORRAL'
#!/usr/bin/env bash
echo "corral $*" >>"$CORRAL_LOG"
exit 0
CORRAL
	run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"no vmtest --fail-marker"* ]]
	! grep -q -- '--bootc' "$CORRAL_LOG"
}

@test "the base contract is selectable" {
	export GUEST_CONSOLE='TUNAOS_BASE_CONTRACT_OK\n'
	DISK_CONTRACT=base run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 0 ]
	grep -q -- '--ready-marker TUNAOS_BASE_CONTRACT_OK' "$CORRAL_LOG"
	DISK_CONTRACT=bogus run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 1 ]
}
