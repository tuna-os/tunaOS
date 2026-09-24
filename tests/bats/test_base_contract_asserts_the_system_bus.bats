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
  "is-system-running")        echo running ;;
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

# ── The bus assertion is reachable on a boot that has not settled ─────────
#
# Every assertion above sat below `systemctl is-system-running --wait`, and
# that wait was on this unit's own job (tunaOS#2514), so the bus check never
# ran on any cell. The contract now samples the state once. `starting` is what
# a base cell samples, because the unit is a job in the boot transaction, and
# the bus assertion has to fire from there.

@test "a dead bus fails the contract while the boot is still starting" {
	STUB_DIR="$(mktemp -d)"
	cat >"${STUB_DIR}/systemctl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "is-system-running --wait") sleep 600 ;;
  "is-system-running")        echo starting; exit 1 ;;
  "show -P Id dbus.service")  echo dbus-broker.service ;;
  "is-active --quiet dbus-broker.service") exit 3 ;;
  "is-active dbus-broker.service")         echo failed ;;
  *) exit 0 ;;
esac
EOF
	printf '#!/usr/bin/env bash\nexit 0\n' >"${STUB_DIR}/bootc"
	chmod +x "${STUB_DIR}/systemctl" "${STUB_DIR}/bootc"
	export PATH="${STUB_DIR}:${PATH}"
	# The outer timeout only stops a regression to `--wait` from hanging the
	# suite; the stub's `--wait` never returns.
	run timeout 20s bash "$SCRIPT" --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"TUNAOS_BASE_CONTRACT_FAIL reason=system-bus-inactive"* ]]
	[[ "$output" != *"system-state="* ]]
}
