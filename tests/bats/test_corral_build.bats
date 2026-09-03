#!/usr/bin/env bats
# Unit tests for scripts/corral-build.sh — the Corral VM build orchestrator
# used by scripts/boot-gate-matrix.sh for boot-gate health checks
# (tuna-os/tunaos#1800).
#
# `corral` and `podman` are stubbed as fake binaries placed early on PATH.
# The corral stub never actually execs the remote `-c` payload it is given
# (there is no real VM) — it just records the invocation and returns a
# configurable exit code, the same pattern used by test_boot_gate_resume.bats.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/corral-build.sh"

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="${TEST_ROOT}/stub-bin"
	mkdir -p "${STUB_BIN}"
	export PATH="${STUB_BIN}:${PATH}"

	# Sandbox HOME/XDG_RUNTIME_DIR so the redfin auth.json lookup never sees
	# real host state.
	export HOME="${TEST_ROOT}/home"
	export XDG_RUNTIME_DIR="${TEST_ROOT}/xdg"
	mkdir -p "${HOME}" "${XDG_RUNTIME_DIR}"

	export CORRAL_LOG="${TEST_ROOT}/corral.log"
	: >"${CORRAL_LOG}"

	# sleep is called bare (`sleep 90`, `sleep 15`) for VM boot/SSH backoff;
	# make it instant so tests don't actually wait.
	cat >"${STUB_BIN}/sleep" <<'SLEEP'
#!/usr/bin/env bash
exit 0
SLEEP
	chmod +x "${STUB_BIN}/sleep"

	# podman is mocked per the issue's scope even though corral-build.sh only
	# references it inside the remote -c payload (never execs it locally).
	cat >"${STUB_BIN}/podman" <<'PODMAN'
#!/usr/bin/env bash
echo "podman $*" >>"${CORRAL_LOG:-/dev/null}"
exit 0
PODMAN
	chmod +x "${STUB_BIN}/podman"

	# corral stub. Behavior is tuned per-test via env vars:
	#   CORRAL_VM_EXISTS      - "0" makes the first `corral list` report no VM
	#                           (default "1": VM already present)
	#   CORRAL_VM_STATUS      - status glyph reported by `corral list`
	#                           (default "●", i.e. already running)
	#   CORRAL_CREATE_RC      - exit code for `corral create`
	#   CORRAL_START_RC       - exit code for `corral start`
	#   CORRAL_SSH_TRUE_RC    - exit code for the SSH-readiness probe (`-c true`)
	#   CORRAL_SYNC_RC        - exit code for the repo-sync ssh command
	#   CORRAL_BUILD_RC       - exit code for every `just build` ssh command
	#   CORRAL_BUILD_FAIL_FLAVOR / CORRAL_BUILD_FAIL_RC
	#                         - make only this one flavor's build fail
	cat >"${STUB_BIN}/corral" <<'CORRAL'
#!/usr/bin/env bash
echo "corral $*" >>"${CORRAL_LOG:-/dev/null}"

case "$1" in
list)
	n=0
	if [[ -n "${CORRAL_LIST_COUNT_FILE:-}" && -f "${CORRAL_LIST_COUNT_FILE}" ]]; then
		n="$(cat "${CORRAL_LIST_COUNT_FILE}")"
	fi
	n=$((n + 1))
	[[ -n "${CORRAL_LIST_COUNT_FILE:-}" ]] && echo "$n" >"${CORRAL_LIST_COUNT_FILE}"

	if [[ "${CORRAL_VM_EXISTS:-1}" == "0" && "$n" -eq 1 ]]; then
		exit 0
	fi
	echo "${CORRAL_VM_NAME:-tunaos-builder}  node  ${CORRAL_VM_STATUS:-●}"
	exit 0
	;;
create)
	exit "${CORRAL_CREATE_RC:-0}"
	;;
start)
	exit "${CORRAL_START_RC:-0}"
	;;
ssh)
	last="${@: -1}"
	case "$last" in
	true)
		exit "${CORRAL_SSH_TRUE_RC:-0}"
		;;
	*"git -C /data clone"*)
		exit "${CORRAL_SYNC_RC:-0}"
		;;
	*"just build"*)
		if [[ -n "${CORRAL_BUILD_FAIL_FLAVOR:-}" && "$last" == *" ${CORRAL_BUILD_FAIL_FLAVOR} "* ]]; then
			exit "${CORRAL_BUILD_FAIL_RC:-1}"
		fi
		exit "${CORRAL_BUILD_RC:-0}"
		;;
	*)
		exit "${CORRAL_SSH_RC:-0}"
		;;
	esac
	;;
*)
	exit 0
	;;
esac
CORRAL
	chmod +x "${STUB_BIN}/corral"
}

teardown() {
	rm -rf "${TEST_ROOT}"
	rm -f /tmp/corral-build-*.log
}

# ── argument parsing / required-arg errors ───────────────────────────────────

@test "corral-build.sh: fails with a usage error when no variant is given" {
	run bash "${SCRIPT}"
	[ "$status" -ne 0 ]
	[[ "$output" == *"Usage"* ]]
}

@test "corral-build.sh: defaults to the gnome flavor when none is given" {
	run bash "${SCRIPT}" yellowfin
	[ "$status" -eq 0 ]
	[[ "$output" == *"Flavors: gnome"* ]]
}

@test "corral-build.sh: expands 'all' to the full desktop flavor list" {
	run bash "${SCRIPT}" yellowfin all
	[ "$status" -eq 0 ]
	[[ "$output" == *"Flavors: gnome kde niri cosmic xfce"* ]]
}

@test "corral-build.sh: builds an explicit multi-flavor list in the given order" {
	run bash "${SCRIPT}" yellowfin kde xfce
	[ "$status" -eq 0 ]
	[[ "$output" == *"Flavors: kde xfce"* ]]
	[[ "$output" == *"Building: yellowfin:kde"* ]]
	[[ "$output" == *"Building: yellowfin:xfce"* ]]
}

@test "corral-build.sh: redfin requires registry auth and fails clearly when absent" {
	run bash "${SCRIPT}" redfin gnome
	[ "$status" -ne 0 ]
	[[ "$output" == *"redfin requires registry.redhat.io auth"* ]]
	# Must fail before the VM is (re)created or the repo is synced.
	! grep -q "corral create" "${CORRAL_LOG}"
	[[ "$output" != *"Syncing repo"* ]]
	[[ "$output" != *"Building:"* ]]
}

# ── VM provisioning / build-dir (remote state) hygiene ───────────────────────

@test "corral-build.sh: creates the builder VM when it does not exist" {
	export CORRAL_VM_EXISTS=0
	export CORRAL_LIST_COUNT_FILE="${TEST_ROOT}/list-count"
	run bash "${SCRIPT}" yellowfin gnome
	[ "$status" -eq 0 ]
	grep -q "corral create tunaos-builder" "${CORRAL_LOG}"
}

@test "corral-build.sh: starts the builder VM when it exists but is stopped" {
	export CORRAL_VM_STATUS="○"
	run bash "${SCRIPT}" yellowfin gnome
	[ "$status" -eq 0 ]
	! grep -q "corral create" "${CORRAL_LOG}"
	grep -q "corral start tunaos-builder" "${CORRAL_LOG}"
}

@test "corral-build.sh: skips create and start when the VM is already running" {
	run bash "${SCRIPT}" yellowfin gnome
	[ "$status" -eq 0 ]
	! grep -q "corral create" "${CORRAL_LOG}"
	! grep -q "corral start" "${CORRAL_LOG}"
}

# ── command failure propagation ───────────────────────────────────────────────

@test "corral-build.sh: aborts with the corral exit code when VM creation fails" {
	export CORRAL_VM_EXISTS=0
	export CORRAL_LIST_COUNT_FILE="${TEST_ROOT}/list-count"
	export CORRAL_CREATE_RC=5
	run bash "${SCRIPT}" yellowfin gnome
	[ "$status" -eq 5 ]
	[[ "$output" != *"Syncing repo"* ]]
	[[ "$output" != *"Building:"* ]]
}

@test "corral-build.sh: aborts with the corral exit code when the repo sync fails" {
	export CORRAL_SYNC_RC=3
	run bash "${SCRIPT}" yellowfin gnome
	[ "$status" -eq 3 ]
	[[ "$output" == *"Syncing repo"* ]]
	# A hard sync failure must abort before any flavor build is attempted.
	[[ "$output" != *"Building:"* ]]
}

@test "corral-build.sh: marks a failed flavor build without aborting the remaining flavors" {
	export CORRAL_BUILD_FAIL_FLAVOR="kde"
	export CORRAL_BUILD_FAIL_RC=2
	run bash "${SCRIPT}" yellowfin gnome kde xfce
	# The per-flavor build is guarded by an if/else, so one bad flavor does
	# not abort the whole run.
	[ "$status" -eq 0 ]
	[[ "$output" == *"Building: yellowfin:gnome"* ]]
	[[ "$output" == *"Building: yellowfin:kde"* ]]
	[[ "$output" == *"Building: yellowfin:xfce"* ]]
	[[ "$output" == *"❌ yellowfin:kde"* ]]
	[[ "$output" == *"✅ yellowfin:gnome"* ]]
	[[ "$output" == *"✅ yellowfin:xfce"* ]]
}

# ── idempotency / stale-state hygiene ─────────────────────────────────────────

@test "corral-build.sh: overwrites the per-flavor build log instead of leaking stale content" {
	local_log="/tmp/corral-build-yellowfin-gnome.log"
	mkdir -p "$(dirname "${local_log}")"
	echo "STALE-FROM-PREVIOUS-RUN" >"${local_log}"

	run bash "${SCRIPT}" yellowfin gnome
	[ "$status" -eq 0 ]

	[ -f "${local_log}" ]
	! grep -q "STALE-FROM-PREVIOUS-RUN" "${local_log}"
}

@test "corral-build.sh: re-running against an already-provisioned VM is idempotent" {
	run bash "${SCRIPT}" yellowfin gnome
	[ "$status" -eq 0 ]
	first_output="$output"

	: >"${CORRAL_LOG}"
	run bash "${SCRIPT}" yellowfin gnome
	[ "$status" -eq 0 ]

	# Neither run should have needed to create or start the VM — it was
	# already up both times.
	! grep -q "corral create" "${CORRAL_LOG}"
	! grep -q "corral start" "${CORRAL_LOG}"
	[[ "$output" == *"Building: yellowfin:gnome"* ]]
	[[ "$first_output" == *"Building: yellowfin:gnome"* ]]
}
