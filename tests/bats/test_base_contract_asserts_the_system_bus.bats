#!/usr/bin/env bats
# The base boot contract must fail an image whose system message bus is dead.
#
# `boots` had a hole big enough to promote a machine with no D-Bus. Measured on
# skipjack, run 34705564876, where BOTH desktops hit the identical failure:
#
#   dbus-broker: Access denied in /etc/selinux/targeted/contexts/dbus_contexts
#             -> dbus.socket: Failed with result 'service-start-limit-hit'
#
#   gnome  gdm depends on dbus.socket -> Dependency failed -> Gate RED
#   kde    emitted its desktop contract marker anyway       -> Gate GREEN
#
# One broken image, two verdicts, and the green one shipped. The contract
# allows `degraded` on purpose (which units may fail is per-variant knowledge),
# and a dead bus hides inside `degraded` on images whose DM does not hard-depend
# on it. So it has to be named explicitly, like `bootc status` already is.
#
# These tests drive the script with stub `systemctl`/`bootc` on PATH, so they
# assert its real behaviour without a VM.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/checks/verify-base-contract.sh"

# $1 = what `systemctl show -P Id dbus.service` prints (the resolved alias)
# $2 = "active" or anything else, for `is-active` on that unit
stub_env() {
	local resolved="$1" bus_state="$2"
	STUB_DIR="$(mktemp -d)"
	cat >"${STUB_DIR}/systemctl" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "is-system-running --wait") echo running ;;
  "show -P Id dbus.service")  echo "${resolved}" ;;
  "is-active --quiet ${resolved}") [[ "${bus_state}" == active ]] && exit 0 || exit 3 ;;
  "is-active ${resolved}")    echo "${bus_state}" ;;
  *) exit 0 ;;
esac
EOF
	printf '#!/usr/bin/env bash\nexit 0\n' >"${STUB_DIR}/bootc"
	chmod +x "${STUB_DIR}/systemctl" "${STUB_DIR}/bootc"
	PATH="${STUB_DIR}:${PATH}"
	export PATH
}

# `|| true`: the last two tests never call stub_env, and a teardown that
# exits non-zero fails the test it was cleaning up after.
teardown() { [[ -n "${STUB_DIR:-}" ]] && rm -rf "${STUB_DIR}"; return 0; }

@test "a healthy system passes and names the bus unit it checked" {
	stub_env dbus-broker.service active
	run bash "$SCRIPT" --runtime
	[ "$status" -eq 0 ]
	[[ "$output" == *"TUNAOS_BASE_CONTRACT_OK"* ]]
	[[ "$output" == *"bus=dbus-broker.service"* ]]
}

@test "a dead system bus fails the contract" {
	# The skipjack:kde case: everything else is fine, the bus is not, and the
	# old contract said OK.
	stub_env dbus-broker.service failed
	run bash "$SCRIPT" --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"TUNAOS_BASE_CONTRACT_FAIL"* ]]
	[[ "$output" == *"system-bus-inactive"* ]]
	[[ "$output" == *"unit=dbus-broker.service"* ]]
}

@test "the alias is resolved, not assumed to be dbus-broker" {
	# Which implementation dbus.service points at is exactly the per-variant
	# detail this check must not care about; hardcoding dbus-broker would pass
	# a dbus-daemon image with a dead bus.
	stub_env dbus-daemon.service failed
	run bash "$SCRIPT" --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"unit=dbus-daemon.service"* ]]

	stub_env dbus-daemon.service active
	run bash "$SCRIPT" --runtime
	[ "$status" -eq 0 ]
	[[ "$output" == *"bus=dbus-daemon.service"* ]]
}

@test "the script reads the bus unit from systemctl rather than a literal" {
	# Guard against the checks above passing because the script hardcodes the
	# same name the stub happens to return (tunaOS#1730).
	grep -qF 'systemctl show -P Id dbus.service' "$SCRIPT"
}

@test "verify-base-contract.sh passes shellcheck" {
	if ! command -v shellcheck &>/dev/null; then skip "shellcheck not installed"; fi
	run shellcheck --severity=error --exclude=SC1091 "$SCRIPT"
	[ "$status" -eq 0 ]
}

# ── The settle wait must be bounded ─────────────────────────────────────────
#
# Every assertion above sits BELOW `systemctl is-system-running --wait`, and
# that wait was unbounded. A machine whose startup never settles never supplies
# a terminal state, so the script hung for the unit's full 300s TimeoutStartSec
# and was killed without printing a line:
#
#   Starting tunaos-base-contract.service - Verify TunaOS base boot contract...
#   [ 314.604325] tunaos-base-contract.service: start operation timed out.
#
# skipjack:gnome, run 34760890405 — and identically in 34705564876, which
# predates the bus assertion, so the hang is older than that check rather than
# caused by it. The cost was double: the gate said "timeout" where the machine
# had a nameable defect, and the bus assertion written for this very failure
# could never reach it.

# A systemctl whose --wait never returns, so the bound is what ends the call.
stub_hanging_settle() {
	STUB_DIR="$(mktemp -d)"
	cat >"${STUB_DIR}/systemctl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "is-system-running --wait") sleep 600 ;;
  "is-system-running")        echo starting ;;
  "show -P Id dbus.service")  echo dbus-broker.service ;;
  "is-active --quiet dbus-broker.service") exit 3 ;;
  "is-active dbus-broker.service")         echo inactive ;;
  *) exit 0 ;;
esac
EOF
	printf '#!/usr/bin/env bash\nexit 0\n' >"${STUB_DIR}/bootc"
	chmod +x "${STUB_DIR}/systemctl" "${STUB_DIR}/bootc"
	export PATH="${STUB_DIR}:${PATH}"
}

@test "a settle wait that never returns is bounded, not left to the unit timeout" {
	stub_hanging_settle
	# The bound is 120s; this must come back far sooner than the 300s that
	# killed the real service. 200s of headroom is plenty to prove the point
	# without making the suite slow.
	run timeout 200s bash "$SCRIPT" --runtime
	[ "$status" -ne 124 ]
	rm -rf "${STUB_DIR}"
}

@test "a hung settle still yields a named verdict, not silence" {
	stub_hanging_settle
	run timeout 200s bash "$SCRIPT" --runtime
	# It says the wait timed out AND what it found when it asked again.
	[[ "$output" == *"settle-wait-timed-out"* ]]
	# And it fails on the state, by name, instead of being killed mid-hang.
	[[ "$output" == *"TUNAOS_BASE_CONTRACT_FAIL"* ]]
	[ "$status" -eq 1 ]
	rm -rf "${STUB_DIR}"
}

@test "degraded is not mistaken for a hang" {
	# `is-system-running` exits non-zero for `degraded`, which this contract
	# ALLOWS. Only timeout(1)'s own 124 means the wait ran out, so a bare
	# `if !` here would have called every degraded boot a hang.
	STUB_DIR="$(mktemp -d)"
	cat >"${STUB_DIR}/systemctl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "is-system-running --wait") echo degraded; exit 1 ;;
  "is-system-running")        echo SHOULD_NOT_BE_CALLED ;;
  "show -P Id dbus.service")  echo dbus-broker.service ;;
  "is-active --quiet dbus-broker.service") exit 0 ;;
  *) exit 0 ;;
esac
EOF
	printf '#!/usr/bin/env bash\nexit 0\n' >"${STUB_DIR}/bootc"
	chmod +x "${STUB_DIR}/systemctl" "${STUB_DIR}/bootc"
	export PATH="${STUB_DIR}:${PATH}"
	run bash "$SCRIPT" --runtime
	[ "$status" -eq 0 ]
	[[ "$output" != *"settle-wait-timed-out"* ]]
	[[ "$output" != *"SHOULD_NOT_BE_CALLED"* ]]
	[[ "$output" == *"TUNAOS_BASE_CONTRACT_OK"* ]]
	rm -rf "${STUB_DIR}"
}
