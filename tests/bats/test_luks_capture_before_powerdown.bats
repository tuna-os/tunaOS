#!/usr/bin/env bats
# The LUKS path must photograph the installed desktop BEFORE the guest is
# powered down (tunaOS#979).
#
# luks-first-boot.py sends `system_powerdown` when it returns unless
# TUNAOS_LUKS_NO_POWEROFF=1. iso-e2e.sh used to set that only for the
# greeter-login phase, so on the default path the installed-desktop capture ran
# 8s into a shutdown. A guest that stopped its display manager inside that
# window left a black framebuffer (stddev=0), and the pixel gate failed the
# cell although the in-guest desktop contract had passed. Run 36873532817
# failed 33 cells that way; the cells that passed were only slower to stop.
#
# These are ordering checks on the shipped script: the race only shows on a
# real guest, and a ~3-hour QEMU cell is not a unit test.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/iso-e2e.sh"

first_line() {
	grep -n -m1 -F -- "$1" "$SCRIPT" | cut -d: -f1
}

@test "luks-first-boot.py is always told to leave the guest running" {
	run grep -c -F 'TUNAOS_LUKS_NO_POWEROFF=1 \' "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$output" -eq 1 ]
	# No conditional form: a value of 0 restores the race.
	run grep -E 'TUNAOS_LUKS_NO_POWEROFF="\$\{' "$SCRIPT"
	[ "$status" -ne 0 ]
}

@test "installed-desktop is captured after first boot and before the powerdown" {
	local boot shot powerdown
	boot="$(first_line 'luks-first-boot.py" \')"
	shot="$(first_line 'screenshot "installed-desktop" || true')"
	[ -n "$boot" ] && [ -n "$shot" ]
	[ "$boot" -lt "$shot" ]
	# The first powerdown sent after the first boot returns must come after
	# the capture.
	powerdown="$(awk -v from="$boot" 'NR > from && /monitor_cmd "system_powerdown"/ { print NR; exit }' "$SCRIPT")"
	[ -n "$powerdown" ]
	[ "$shot" -lt "$powerdown" ]
}

@test "the default path still powers the guest down gracefully" {
	# Without the greeter-login phase, the harness must send the powerdown
	# itself, so swtpm state and LUKS metadata flush before the kill. The
	# TPM auto-unlock boot reuses that swtpm state.
	local shot
	shot="$(first_line 'screenshot "installed-desktop" || true')"
	run awk -v from="$shot" '
		NR > from && /^\t\tfi$/ { closed = 1 }
		closed && /^\t\tmonitor_cmd "system_powerdown"/ { print NR; exit }
	' "$SCRIPT"
	[ "$status" -eq 0 ]
	[ -n "$output" ]
}
