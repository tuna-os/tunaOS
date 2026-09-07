#!/usr/bin/env bats
# The graphical.target assertions must be able to FAIL for a real reason.
#
# WHY THIS EXISTS: both of them were permanently red.
#
# `systemctl is-active graphical.target` was asserted from
# tunaos-desktop-contract.service, which is WantedBy=graphical.target — so it
# runs INSIDE that target's own startup transaction, and a target is not
# `active` until every unit wanting it has finished. It reported `activating`
# and structurally always would. MEASURED on two LUKS installs that otherwise
# passed end-to-end: marlin:cosmic at 11.7s under greetd, marlin:kde at 12.4s
# under sddm — same failure, both desktops, different display managers.
#
# `systemd-analyze verify --recursive-errors=yes graphical.target` failed for
# an unrelated reason: with `yes`, a warning in ANY transitively reachable
# unit fails it, including upstream units we neither ship nor can fix.
# Measured on a dev host: "flatpak-appstream-refresh.service:7: Unknown key
# 'ExecCondition'" is on its own enough to turn it red.
#
# An assertion that always says the same thing cannot report a regression —
# the same defect as the installer GUI gate that could neither pass nor fail.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CHECKS="${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"
RUNTIME="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"

# The predicate the script uses: not-failed, evaluated against a stub whose
# is-failed behaves like the real one (exit 0 only when the unit has failed).
state_predicate() {
	local state="$1"
	bash -c "
systemctl() {
  if [[ \"\$1\" == is-failed ]]; then [[ '$state' == failed ]] && return 0 || return 1; fi
  return 0
}
! systemctl is-failed --quiet graphical.target"
}

@test "the check does not assert is-active on graphical.target" {
	# The exact assertion that could never pass from inside the transaction.
	! grep -qE '^\s*systemctl is-active graphical\.target\s*$' "$CHECKS"
	# ...nor the ActiveState form that replaced it and still failed good boots.
	! grep -q 'active|activating|reloading' "$CHECKS"
}

@test "the reason it cannot: the unit is WantedBy the target it asserts on" {
	# If this ordering ever changes, the comment in the check stops being true
	# and the assertion could legitimately be tightened back to is-active.
	grep -q 'WantedBy=graphical.target' "$RUNTIME"
	grep -q 'e2e-runtime-checks' "$RUNTIME"
}

@test "every non-failed state passes, whenever we happen to sample" {
	# MEASURED on a marlin:niri installed boot: ActiveState was `inactive` at
	# 10.9s with `system state: starting` — a healthy system, sampled before
	# graphical.target had even been queued. An earlier version of this fix
	# accepted active/activating/reloading and rejected inactive; that failed
	# good boots. ActiveState cannot separate healthy from broken here at ANY
	# tolerance, because its value depends on when this unit is sampled and
	# the unit cannot control that.
	state_predicate active
	state_predicate activating
	state_predicate inactive
}

@test "a genuinely failed target still fails" {
	# The check must not have been softened into always passing, which would
	# swap one useless assertion for another.
	! state_predicate failed
}

@test "the default-target assertion is time-independent" {
	# ActiveState depends on when in the boot you ask; get-default does not.
	# This is the half of the original intent that is actually stable.
	grep -q 'systemctl get-default' "$CHECKS"
	grep -q 'graphical.target is the default target' "$CHECKS"
}

@test "the unit-graph gate verifies our unit, not the whole upstream world" {
	# --recursive-errors=yes fails on warnings in units we do not ship, so the
	# GATE line (the one passed to check()) must use =no. The line after the
	# check() call is the command it runs.
	local gate
	gate="$(grep -A1 'check "systemd unit graph verifies' "$CHECKS" | tail -1)"
	[[ "$gate" == *"--recursive-errors=no"* ]]
	[[ "$gate" != *"--recursive-errors=yes"* ]]
	# bootc images strip man pages; systemd-analyze's man-EXISTENCE check then
	# fails with "'(man)' failed with exit status 1", which was enough on its
	# own to keep this gate red on marlin:niri even after the recursive-errors
	# narrowing. A missing man page is not a unit defect.
	[[ "$gate" == *"--man=no"* ]]
}

@test "the transitive sweep is kept, but as information" {
	# Worth reading, not worth failing a build over — and printing it beats
	# the previous behaviour of discarding the output into /dev/null.
	grep -q 'recursive-errors=yes' "$CHECKS"
	grep -q 'systemd-analyze warnings across the graphical.target graph' "$CHECKS"
	# ...and it must never abort the remaining checks.
	grep -q 'analyze_warnings=$(systemd-analyze verify --man=no --recursive-errors=yes graphical.target 2>&1 || true)' "$CHECKS"
}

@test "the script is still valid bash" {
	bash -n "$CHECKS"
}

# The string checks above pin the shape; this one runs the real script.
runtime_stubs() {
	local graphical_state="$1"
	eval "systemctl() {
		case \"\$1\" in
		is-system-running) echo running ;;
		is-active) echo active ;;
		is-failed) [[ "${graphical_state}" == failed ]] && return 0 || return 1 ;;
		show)
			case \" \$* \" in
			*\" ActiveState \"*) echo ${graphical_state} ;;
			*) echo gdm.service ;;
			esac
			;;
		get-default) echo graphical.target ;;
		list-unit-files) : ;;
		--failed) : ;;
		esac
		return 0
	}"
	findmnt() { echo overlay; return 0; }
	bootc() { echo 'Image: ghcr.io/tuna-os/x:y'; return 0; }
	systemd-analyze() { return 0; }
	rpm() { seq 200; }
	locale() { return 0; }
	hostname() { echo tunaos-e2e; }
	export -f systemctl findmnt bootc systemd-analyze rpm locale hostname
}

@test "end to end: a still-starting boot is not red" {
	# The measured real-world state — inactive at 10.9s on a healthy system.
	runtime_stubs inactive
	run bash "$CHECKS" gnome
	[ "$status" -eq 0 ]
	[[ "$output" == *"ok - graphical.target has not failed"* ]]
	[[ "$output" == *"ok - graphical.target is the default target"* ]]
	[[ "$output" != *"not ok - "* ]]
}

@test "end to end: a failed target is still reported" {
	# Proof the fix did not just make the assertion unconditionally true.
	runtime_stubs failed
	run bash "$CHECKS" gnome
	[ "$status" -ne 0 ]
	[[ "$output" == *"not ok - graphical.target has not failed"* ]]
}
