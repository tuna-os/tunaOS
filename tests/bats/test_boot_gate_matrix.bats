#!/usr/bin/env bats
# Unit tests for scripts/boot-gate-matrix.sh — the parallel gate fan-out
# runner that round-robins scripts/boot-gate.sh across the KubeVirt node
# pool with bounded concurrency. tuna-os/tunaos#1798.
#
# These tests exercise the matrix's OWN logic (flavor expansion, concurrency
# budgeting, node round-robin, failure aggregation, env-var defaults/invalid
# input) without a live cluster or a real corral binary. No behavior change
# to the script is made here — only tests.
#
# Two dependency boundaries are stubbed:
#  - `corral` on PATH: the matrix script only probes `command -v corral`
#    before doing anything else, so a no-op stub is enough to satisfy it.
#  - `scripts/boot-gate.sh`: the matrix invokes this as a *relative* path
#    from the repo root it cd's into (`cd "$(dirname BASH_SOURCE)/.."`), so
#    to control it we stage a throwaway copy of the repo with
#    boot-gate-matrix.sh alongside a stub boot-gate.sh. The stub records
#    each invocation (target, node, env) and tracks in-flight concurrency
#    via a flock-guarded counter, standing in for what would otherwise be
#    real corral/SSH calls (model: test_boot_gate_resume.bats, which stubs
#    corral directly one layer down).

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
MATRIX_SRC="${REPO_ROOT}/scripts/boot-gate-matrix.sh"

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="${TEST_ROOT}/stub-bin"
	STAGE="${TEST_ROOT}/stage"
	STUB_LOGDIR="${TEST_ROOT}/logs"
	mkdir -p "${STUB_BIN}" "${STAGE}/scripts" "${STUB_LOGDIR}"
	export PATH="${STUB_BIN}:${PATH}"
	export STUB_LOGDIR

	# no-op corral: the matrix only checks `command -v corral` for itself;
	# the actual gate work happens in the stubbed boot-gate.sh below.
	cat >"${STUB_BIN}/corral" <<'CORRAL'
#!/usr/bin/env bash
exit 0
CORRAL
	chmod +x "${STUB_BIN}/corral"

	# Stage a throwaway copy of the matrix script so it cd's into $STAGE
	# (dirname of BASH_SOURCE/..) and calls our stub ./scripts/boot-gate.sh
	# instead of the real one.
	cp "${MATRIX_SRC}" "${STAGE}/scripts/boot-gate-matrix.sh"
	chmod +x "${STAGE}/scripts/boot-gate-matrix.sh"

	# Stub boot-gate.sh: stands in for the real corral/SSH-driven gate.
	# Records $1:$2 (variant:flavor), the CORRAL_NODE/GATE_NAME/GATE_TIMEOUT/
	# REPO_ORGANIZATION env vars the matrix exports per-launch, and the
	# peak number of concurrent invocations. Sleeps $STUB_SLEEP (default
	# 0.2s) to give overlapping launches a window to collide. Fails for any
	# target listed (comma-separated) in $STUB_FAIL_TARGETS.
	cat >"${STAGE}/scripts/boot-gate.sh" <<'GATE'
#!/usr/bin/env bash
set -euo pipefail
VARIANT="${1:?}"
FLAVOR="${2:-gnome}"
TARGET="${VARIANT}:${FLAVOR}"
LOCK="${STUB_LOGDIR}/lock"
COUNTFILE="${STUB_LOGDIR}/count"
MAXFILE="${STUB_LOGDIR}/max"
CALLLOG="${STUB_LOGDIR}/calls.log"

{
	flock -x 200
	cur=$(cat "${COUNTFILE}" 2>/dev/null || echo 0)
	cur=$((cur + 1))
	echo "${cur}" >"${COUNTFILE}"
	max=$(cat "${MAXFILE}" 2>/dev/null || echo 0)
	[[ ${cur} -gt ${max} ]] && echo "${cur}" >"${MAXFILE}"
	echo "${TARGET} node=${CORRAL_NODE:-} name=${GATE_NAME:-} org=${REPO_ORGANIZATION:-} timeout=${GATE_TIMEOUT:-}" >>"${CALLLOG}"
} 200>"${LOCK}"

sleep "${STUB_SLEEP:-0.2}"

{
	flock -x 200
	cur=$(cat "${COUNTFILE}" 2>/dev/null || echo 0)
	cur=$((cur - 1))
	echo "${cur}" >"${COUNTFILE}"
} 200>"${LOCK}"

rc=0
IFS=',' read -r -a fails <<<"${STUB_FAIL_TARGETS:-}"
for f in "${fails[@]}"; do
	[[ "${f}" == "${TARGET}" ]] && rc=1
done
exit "${rc}"
GATE
	chmod +x "${STAGE}/scripts/boot-gate.sh"

	MATRIX="${STAGE}/scripts/boot-gate-matrix.sh"
}

teardown() {
	rm -rf "${TEST_ROOT}"
}

calls() { cat "${STUB_LOGDIR}/calls.log" 2>/dev/null; }
call_count() { calls | wc -l | tr -d '[:space:]'; }
peak_concurrency() { cat "${STUB_LOGDIR}/max" 2>/dev/null || echo 0; }

# ── flavor expansion (GATE_FLAVORS) ─────────────────────────────────────────

@test "matrix: bare variant expands to the default flavor set" {
	run bash "${MATRIX}" yellowfin
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 5 ]
	for f in gnome kde cosmic niri xfce; do
		calls | grep -q "^yellowfin:${f} "
	done
	[[ "$output" == *"5 target(s)"* ]]
}

@test "matrix: variant:flavor pair bypasses expansion (exactly one gate)" {
	run bash "${MATRIX}" yellowfin:gnome
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 1 ]
	calls | grep -q "^yellowfin:gnome "
}

@test "matrix: mixes explicit pairs and bare-variant expansion in one invocation" {
	run bash "${MATRIX}" yellowfin:gnome albacore
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 6 ] # 1 explicit + 5 expanded
	calls | grep -q "^yellowfin:gnome "
	for f in gnome kde cosmic niri xfce; do
		calls | grep -q "^albacore:${f} "
	done
}

@test "matrix: GATE_FLAVORS overrides the default set for bare variants (space-separated)" {
	GATE_FLAVORS="gnome kde" run bash "${MATRIX}" yellowfin
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 2 ]
	calls | grep -q "^yellowfin:gnome "
	calls | grep -q "^yellowfin:kde "
}

@test "matrix: GATE_FLAVORS does not split on commas (word-splitting is whitespace-only)" {
	# The script expands flavors with an unquoted `for f in $DEFAULT_FLAVORS`
	# loop, which only splits on IFS whitespace — a comma-joined list is a
	# single literal flavor token. Documenting the actual behavior so a
	# future change to comma-splitting is a deliberate, visible diff here.
	GATE_FLAVORS="gnome,kde" run bash "${MATRIX}" yellowfin
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 1 ]
	calls | grep -q "^yellowfin:gnome,kde "
}

@test "matrix: explicit target flavor is used verbatim, ignoring GATE_FLAVORS" {
	GATE_FLAVORS="gnome kde" run bash "${MATRIX}" yellowfin:niri
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 1 ]
	calls | grep -q "^yellowfin:niri "
}

# ── concurrency budgeting (GATE_CONCURRENCY) ────────────────────────────────

@test "matrix: bounds in-flight gates to the default concurrency of 3" {
	STUB_SLEEP=0.3 run bash "${MATRIX}" yellowfin
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 5 ]
	[ "$(peak_concurrency)" -le 3 ]
}

@test "matrix: GATE_CONCURRENCY raises the in-flight bound" {
	GATE_CONCURRENCY=5 STUB_SLEEP=0.3 run bash "${MATRIX}" yellowfin
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 5 ]
	[ "$(peak_concurrency)" -eq 5 ]
}

@test "matrix: GATE_CONCURRENCY=1 serializes gates (never more than one in flight)" {
	GATE_CONCURRENCY=1 STUB_SLEEP=0.2 run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic
	[ "$status" -eq 0 ]
	[ "$(call_count)" -eq 3 ]
	[ "$(peak_concurrency)" -eq 1 ]
}

@test "matrix: reports the configured concurrency in its banner" {
	GATE_CONCURRENCY=7 run bash "${MATRIX}" yellowfin:gnome
	[ "$status" -eq 0 ]
	[[ "$output" == *"concurrency=7"* ]]
}

# ── node round-robin (GATE_NODES) ───────────────────────────────────────────

@test "matrix: round-robins targets across GATE_NODES (space-separated)" {
	GATE_NODES="node-a node-b" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic yellowfin:niri
	[ "$status" -eq 0 ]
	calls | grep "^yellowfin:gnome " | grep -q "node=node-a"
	calls | grep "^yellowfin:kde " | grep -q "node=node-b"
	calls | grep "^yellowfin:cosmic " | grep -q "node=node-a"
	calls | grep "^yellowfin:niri " | grep -q "node=node-b"
}

@test "matrix: round-robins across GATE_NODES given as a comma list" {
	GATE_NODES="node-a,node-b,node-c" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic yellowfin:niri
	[ "$status" -eq 0 ]
	calls | grep "^yellowfin:gnome " | grep -q "node=node-a"
	calls | grep "^yellowfin:kde " | grep -q "node=node-b"
	calls | grep "^yellowfin:cosmic " | grep -q "node=node-c"
	calls | grep "^yellowfin:niri " | grep -q "node=node-a"
}

@test "matrix: round-robins across a mixed comma/space GATE_NODES list" {
	GATE_NODES="node-a, node-b node-c" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic
	[ "$status" -eq 0 ]
	calls | grep "^yellowfin:gnome " | grep -q "node=node-a"
	calls | grep "^yellowfin:kde " | grep -q "node=node-b"
	calls | grep "^yellowfin:cosmic " | grep -q "node=node-c"
}

@test "matrix: a single GATE_NODES entry pins every gate to that node" {
	GATE_NODES="only-node" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic
	[ "$status" -eq 0 ]
	[ "$(calls | grep -c 'node=only-node')" -eq 3 ]
}

@test "matrix: with no GATE_NODES and no kubectl, gates run with no node pin" {
	# PATH only contains our stub-bin (plus system PATH via setup, which may
	# still have kubectl); force the auto-detect branch to see an empty pool
	# by asserting on an explicitly empty GATE_NODES instead, which takes
	# the same code path as "no nodes discovered".
	GATE_NODES="" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde
	[ "$status" -eq 0 ]
	calls | grep "^yellowfin:gnome " | grep -q "node= "
	calls | grep "^yellowfin:kde " | grep -q "node= "
}

# ── failure aggregation ──────────────────────────────────────────────────────

@test "matrix: passes and exits 0 when every gate succeeds" {
	run bash "${MATRIX}" yellowfin:gnome yellowfin:kde
	[ "$status" -eq 0 ]
	[[ "$output" == *"all 2 gate(s) PASSED"* ]]
}

@test "matrix: a single failing gate fails the whole matrix" {
	STUB_FAIL_TARGETS="yellowfin:kde" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic
	[ "$status" -eq 1 ]
	[[ "$output" == *"1/3 gate(s) FAILED"* ]]
	[[ "$output" == *"❌ yellowfin:kde"* ]]
	[[ "$output" == *"✅ yellowfin:gnome"* ]]
	[[ "$output" == *"✅ yellowfin:cosmic"* ]]
}

@test "matrix: multiple failing gates are all aggregated into the failure count" {
	STUB_FAIL_TARGETS="yellowfin:gnome,yellowfin:cosmic" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic
	[ "$status" -eq 1 ]
	[[ "$output" == *"2/3 gate(s) FAILED"* ]]
}

@test "matrix: all gates failing still reports every target and a non-zero exit" {
	STUB_FAIL_TARGETS="yellowfin:gnome,yellowfin:kde" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde
	[ "$status" -eq 1 ]
	[[ "$output" == *"2/2 gate(s) FAILED"* ]]
}

@test "matrix: failure in one gate does not prevent later gates from launching" {
	# With concurrency=1 the failing gate finishes before the next launches;
	# confirms failure of an earlier gate doesn't abort the fan-out loop.
	GATE_CONCURRENCY=1 STUB_FAIL_TARGETS="yellowfin:gnome" run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic
	[ "$status" -eq 1 ]
	[ "$(call_count)" -eq 3 ]
	[[ "$output" == *"1/3 gate(s) FAILED"* ]]
}

# ── env-var defaults and invalid-input handling ─────────────────────────────

@test "matrix: exits 77 when corral is not installed" {
	rm -f "${STUB_BIN}/corral"
	run bash "${MATRIX}" yellowfin:gnome
	[ "$status" -eq 77 ]
	[[ "$output" == *"corral not installed"* ]]
}

@test "matrix: exits 2 with no targets given" {
	run bash "${MATRIX}"
	[ "$status" -eq 2 ]
	[[ "$output" == *"no targets given"* ]]
}

@test "matrix: passes GATE_TIMEOUT and REPO_ORGANIZATION through to each gate" {
	GATE_TIMEOUT=42 REPO_ORGANIZATION=acme run bash "${MATRIX}" yellowfin:gnome
	[ "$status" -eq 0 ]
	calls | grep -q "timeout=42"
	calls | grep -q "org=acme"
}

@test "matrix: defaults GATE_TIMEOUT and REPO_ORGANIZATION when unset" {
	run bash "${MATRIX}" yellowfin:gnome
	[ "$status" -eq 0 ]
	calls | grep -q "timeout=1200"
	calls | grep -q "org=tuna-os"
}

@test "matrix: gives each launch a unique GATE_NAME" {
	run bash "${MATRIX}" yellowfin:gnome yellowfin:kde yellowfin:cosmic
	[ "$status" -eq 0 ]
	local names
	names=$(calls | grep -o 'name=[^ ]*' | sort -u | wc -l | tr -d '[:space:]')
	[ "$names" -eq 3 ]
}
