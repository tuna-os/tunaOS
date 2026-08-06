#!/usr/bin/env bats
# The serial console is the only channel out of an installed TunaOS system, so
# a fact it does not carry is unrecoverable after the run ends. guppy:xfce
# failed the LUKS gate at "Connection timed out during banner exchange" with
# "Started OpenSSH server daemon" logged, no failed unit, and "a network
# manager is active" passing — evidence equally consistent with the guest
# holding no address and with nothing bound to :22, and the serial could not
# tell them apart. e2e-runtime-checks.sh now emits both.
#
# These tests execute the emitting block rather than grepping the file for it.
# A grep here would match the explanatory comment above the code and pass
# while the code was gone — that exact false pass has happened in this repo.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"

# Extract the reachability block verbatim from the real script, so these tests
# run the shipped code and not a copy that can drift away from it.
#
# The end anchor counts the two `fi`s at this indent level rather than matching
# any message text. Anchoring on a message would couple extraction to the very
# strings these tests assert about: mutating one would break the extraction and
# fail every test with "block not found", hiding which assertion actually
# caught the change.
extract_block() {
	awk '
		/^\tif command -v ip /  { f = 1 }
		f                       { print }
		f && /^\tfi$/           { if (++n == 2) exit }
	' "$SCRIPT"
}

# Run the block with `emit` stubbed to plain echo and PATH set to $1, so the
# presence or absence of ip(8)/ss(8) is what the test controls.
run_block() {
	local path="$1"
	local block
	block="$(extract_block)"
	[ -n "$block" ] || return 90
	PATH="$path" bash -c "emit() { echo \"\$1\"; }; $block"
}

setup() {
	STUBS="$BATS_TEST_TMPDIR/stubs"
	mkdir -p "$STUBS"
}

@test "reachability block is present and extractable" {
	run extract_block
	[ "$status" -eq 0 ]
	[[ "$output" == *"ipv4:"* ]]
	[[ "$output" == *"tcp listeners:"* ]]
}

@test "reports the guest's address and listeners when ip and ss exist" {
	cat >"$STUBS/ip" <<-'EOF'
		#!/bin/sh
		echo "enp0s3           UP             10.0.2.15/24"
	EOF
	cat >"$STUBS/ss" <<-'EOF'
		#!/bin/sh
		echo "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*"
	EOF
	chmod +x "$STUBS/ip" "$STUBS/ss"

	run run_block "$STUBS:/usr/bin:/bin"
	[ "$status" -eq 0 ]
	[[ "$output" == *"10.0.2.15/24"* ]]
	[[ "$output" == *"0.0.0.0:22"* ]]
}

# The whole point of the listener line is to distinguish "nothing is listening"
# from "we could not look". If a missing ss(8) rendered as an empty list, it
# would assert the first while meaning the second — the wrong diagnosis, stated
# confidently, which is worse than no line at all.
@test "a missing ss(8) says so instead of reporting an empty listener list" {
	cat >"$STUBS/ip" <<-'EOF'
		#!/bin/sh
		echo "enp0s3           UP             10.0.2.15/24"
	EOF
	chmod +x "$STUBS/ip"

	run run_block "$STUBS:/usr/bin:/bin"
	[ "$status" -eq 0 ]
	[[ "$output" == *"ss(8) unavailable"* ]]
	# and must not emit a bare, empty listener list
	[[ "$output" != *"tcp listeners: "$'\n'* ]]
}

@test "a missing ip(8) says so instead of reporting no addresses" {
	cat >"$STUBS/ss" <<-'EOF'
		#!/bin/sh
		echo "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*"
	EOF
	chmod +x "$STUBS/ss"

	run run_block "$STUBS:/usr/bin:/bin"
	[ "$status" -eq 0 ]
	[[ "$output" == *"ip(8) unavailable"* ]]
}

# Informational, never an assertion: a production image ships sshd off with
# nothing listening, and this script runs on every real user boot. Emitting
# "not ok" there would fail the desktop contract on a correctly hardened
# system.
@test "reachability lines are informational, not TAP assertions" {
	run extract_block
	[ "$status" -eq 0 ]
	[[ "$output" != *"check \""* ]]
	[[ "$output" != *"not ok"* ]]
}
