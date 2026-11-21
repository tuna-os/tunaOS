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
	export BASE_CONTRACT_GRACE=2 BRANDING_GRACE=2
	unset TUNAOS_QCOW2_FILESYSTEM DISK_CONTRACT BRANDING_GATE

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
	run bash "$GATE_SCRIPT" ghcr.io/tuna-os/yellowfin:gnome-candidate "$OUT" 600
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

# ── Runtime branding contract (verify-branding --runtime) ───────────────────
REPORT_FAIL='TUNAOS_BRANDING_REPORT {"schema":1,"variant":"yellowfin","result":"fail","failed":["hostname","boot.efi"],"checks":[{"id":"hostname","status":"fail","detail":"localhost"}]}'

@test "report mode records a branding FAIL without failing the gate" {
	# Falsification: let the report-mode branch set rc=1, or drop the
	# verdict writer, and status or the verdict file changes.
	export GUEST_CONSOLE="TUNAOS_BASE_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_OK\n${REPORT_FAIL}\r\nTUNAOS_BRANDING_FAIL variant=yellowfin desktop=gnome failed=hostname,boot.efi\r\n"
	run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 0 ]
	[ "$(cat "$OUT/branding-verdict.txt")" = "status=fail failed=hostname,boot.efi" ]
	python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["failed"]==["hostname","boot.efi"], d; assert d["checks"][0]["id"]=="hostname"' "$OUT/branding-report.json"
	[[ "$output" == *"branding: status=fail failed=hostname,boot.efi (BRANDING_GATE=report)"* ]]
}

@test "block mode fails the gate on a branding FAIL and hands corral the marker" {
	# Falsification: drop the block-mode FAIL pattern or the rc=1 and this passes.
	export GUEST_CONSOLE="TUNAOS_BASE_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_OK\n${REPORT_FAIL}\nTUNAOS_BRANDING_FAIL variant=yellowfin desktop=gnome failed=hostname,boot.efi\n"
	BRANDING_GATE=block run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 1 ]
	grep -q -- '|TUNAOS_BRANDING(_\[A-Z\]+)?_FAIL' "$CORRAL_LOG"
	[[ "$output" == *"runtime branding contract did not pass: status=fail"* ]]
}

@test "block mode fails a boot whose image never printed a branding verdict" {
	# Falsification: treat absent as ok in block mode and status becomes 0.
	export GUEST_CONSOLE='TUNAOS_BASE_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_OK\n'
	BRANDING_GATE=block run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 1 ]
	[ "$(cat "$OUT/branding-verdict.txt")" = "status=absent failed=-" ]
	[[ "$output" == *"no TUNAOS_BRANDING_OK|FAIL within 2s"* ]]
}

@test "block mode passes a branded boot and keeps the report as evidence" {
	# Falsification: match the REPORT line as a verdict and the OK is lost.
	export GUEST_CONSOLE='TUNAOS_BASE_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_OK\nTUNAOS_BRANDING_REPORT {"schema":1,"result":"ok","failed":[],"checks":[]}\nTUNAOS_BRANDING_OK variant=yellowfin desktop=gnome checks=14 skipped=1\n'
	BRANDING_GATE=block run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 0 ]
	[ "$(cat "$OUT/branding-verdict.txt")" = "status=ok failed=-" ]
	python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["result"]=="ok" and d["verdict"]["checks"]=="14", d' "$OUT/branding-report.json"
}

@test "an interleaved, unparsable report still yields the verdict line's result" {
	# Falsification: derive the verdict from the JSON alone and this reads absent.
	export GUEST_CONSOLE='TUNAOS_DESKTOP_CONTRACT_OK\nTUNAOS_BASE_CONTRACT_OK\nTUNAOS_BRANDING_REPORT {"schema":1,"res[   12.3] kernel: noise\nTUNAOS_BRANDING_FAIL variant=bonito desktop=niri failed=flatpak.remotes\n'
	run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 0 ]
	[ "$(cat "$OUT/branding-verdict.txt")" = "status=fail failed=flatpak.remotes" ]
	python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["report"]=="unparsable" and d["failed"]==["flatpak.remotes"], d' "$OUT/branding-report.json"
}

@test "an unknown BRANDING_GATE is refused, not defaulted" {
	# Falsification: fall through to report for unknown values and status is 0.
	export GUEST_CONSOLE='TUNAOS_BASE_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_OK\n'
	BRANDING_GATE=warn run bash "$GATE_SCRIPT" img "$OUT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"BRANDING_GATE must be 'report' or 'block'"* ]]
	! grep -q -- '--bootc' "$CORRAL_LOG"
}

@test "the Gate and the PR boot gate run in block mode and sudo keeps it" {
	# Falsification: drop BRANDING_GATE: block from either Corral step, or leave
	# it off sudo's --preserve-env, and the script falls back to report there.
	local wf="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
	[ "$(grep -c '^          BRANDING_GATE: block$' "$wf")" -eq 2 ]
	[ "$(grep -c -- '--preserve-env=[A-Z0-9_,]*BRANDING_GATE' "$wf")" -eq 2 ]
	[ "$(grep -c 'corral-boot-gate.sh "\$\(IMAGE\|TEST_IMAGE\)"' "$wf")" -eq 2 ]
}
