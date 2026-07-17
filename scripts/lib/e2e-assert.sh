#!/bin/bash
# TAP-style assertion helpers for on-VM E2E check scripts (run over SSH
# against a booted/installed guest). Adapted from frostyard/snosi's
# test/lib/helpers.sh (LGPL-2.1-or-later): a `check()` function that runs a
# command and records ok/not-ok, plus `print_summary` which exits with the
# failure count so the caller (an SSH exit code) can tell pass from fail.
#
# Usage: source this from a check script, call check "description" cmd...
# for each assertion, then print_summary at the end.

PASS=0
FAIL=0

check() {
	local desc="$1"
	shift
	if "$@" >/dev/null 2>&1; then
		echo "ok - $desc"
		PASS=$((PASS + 1))
	else
		echo "not ok - $desc"
		FAIL=$((FAIL + 1))
	fi
}

print_summary() {
	echo ""
	echo "# Results: $PASS passed, $FAIL failed, $((PASS + FAIL)) total"
	exit "$FAIL"
}
