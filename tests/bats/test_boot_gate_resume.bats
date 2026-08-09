#!/usr/bin/env bats
# Unit tests for scripts/boot-gate.sh — the corral boot-gate runner, focused
# on the --resume retry path for tuna-os/tunaOS#627 (KubeVirt virt-launcher
# teardown destroys the builder's serial log before corral reads the build
# marker, so a finished build can fail with "builder VM ended (Succeeded)
# without a build marker" even though the disk PVC is valid).

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
GATE_SCRIPT="${REPO_ROOT}/scripts/boot-gate.sh"

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="${TEST_ROOT}/stub-bin"
	mkdir -p "${STUB_BIN}"
	export PATH="${STUB_BIN}:${PATH}"

	# Default stubs: corral create succeeds on first try, ssh answers, delete
	# cleans up. Individual tests override create/resume/start as needed.
	cat >"${STUB_BIN}/corral" <<'CORRAL'
#!/usr/bin/env bash
echo "corral $*" >>"${CORRAL_LOG:-/dev/null}"
case "$1" in
create)
	# Version probe: the gate requires --bootc in `corral create --help`.
	if [[ "$*" == *"--help"* ]]; then
		echo "  --bootc  Bootc container image to run"
		exit 0
	fi
	# First arg after subcommand is the VM name; --bootc means the gate path.
	exit "${CORRAL_CREATE_RC:-0}"
	;;
bootc) exit "${CORRAL_BOOTC_RC:-0}" ;;
start) exit 0 ;;
ssh)
	# Desktop checks probe `systemctl is-active ...`; answer active.
	if [[ "$*" == *"is-active"* ]]; then
		echo "active"
		exit 0
	fi
	exit "${CORRAL_SSH_RC:-0}"
	;;
delete) exit 0 ;;
*) exit 0 ;;
esac
CORRAL
	chmod +x "${STUB_BIN}/corral"

	export CORRAL_LOG="${TEST_ROOT}/corral.log"
}

teardown() {
	rm -rf "${TEST_ROOT}"
}

@test "boot-gate.sh: passes through when corral create succeeds" {
	run bash "${GATE_SCRIPT}" yellowfin gnome
	[ "$status" -eq 0 ]
	grep -q "create" "${CORRAL_LOG}"
	grep -q -- "--resume" "${CORRAL_LOG}" && return 1 || true
	[[ "$output" == *"boot-gate PASS"* ]]
}

@test "boot-gate.sh: retries with --resume when create fails and resume succeeds" {
	export CORRAL_CREATE_RC=1
	export CORRAL_BOOTC_RC=0
	run bash "${GATE_SCRIPT}" yellowfin gnome
	[ "$status" -eq 0 ]
	grep -q "bootc create" "${CORRAL_LOG}"
	grep -q -- "--resume" "${CORRAL_LOG}"
	grep -q "start" "${CORRAL_LOG}"
	[[ "$output" == *"--resume from the completed disk"* ]]
	[[ "$output" == *"boot-gate PASS"* ]]
}

@test "boot-gate.sh: fails when both create and resume fail" {
	export CORRAL_CREATE_RC=1
	export CORRAL_BOOTC_RC=1
	run bash "${GATE_SCRIPT}" yellowfin gnome
	[ "$status" -ne 0 ]
	[[ "$output" == *"no resumable build was found"* ]]
}

@test "boot-gate.sh: fails when SSH never answers after resume" {
	export CORRAL_CREATE_RC=1
	export CORRAL_BOOTC_RC=0
	export CORRAL_SSH_RC=1
	export GATE_TIMEOUT=15
	run bash "${GATE_SCRIPT}" yellowfin gnome
	[ "$status" -ne 0 ]
	[[ "$output" == *"SSH not reachable after --resume"* ]]
}
