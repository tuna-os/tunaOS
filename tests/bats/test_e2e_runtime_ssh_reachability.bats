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

# Absolute, because a `PATH=<dir> cmd` prefix also governs the lookup of `cmd`
# itself: with the block's PATH set to the stub directory alone, a bare `bash`
# would have to live in there too.
BASH_BIN="$(command -v bash)"

# The utilities the extracted block itself shells out to. They have to be
# reachable or the block cannot run, but they must arrive through the test's own
# bin directory: the moment /usr/bin is on the block's PATH to supply them, it
# supplies the host's real ip(8) and ss(8) as well. See setup().
BLOCK_UTILS=(tr awk sort)

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
	PATH="$path" "$BASH_BIN" -c "emit() { echo \"\$1\"; }; $block"
}

setup() {
	STUBS="$BATS_TEST_TMPDIR/stubs"
	mkdir -p "$STUBS"
	# $STUBS is the block's ENTIRE PATH. It used to be "$STUBS:/usr/bin:/bin",
	# which meant the two "unavailable" cases below asserted nothing on any host
	# that has iproute2: `command -v ss` found /usr/bin/ss even though the test
	# installs no ss stub, so the else-branch never ran and the real listener
	# list was reported instead. That is a host-dependent test: it passed only
	# where iproute2 is absent, and failed on GitHub's runners, which ship it.
	#
	# So the helper utilities the block needs are symlinked in individually
	# rather than borrowed from a directory that also holds ip(8) and ss(8).
	local u bin
	for u in "${BLOCK_UTILS[@]}"; do
		bin="$(command -v "$u")" || {
			echo "missing utility the reachability block needs: $u" >&2
			return 1
		}
		ln -sf "$bin" "$STUBS/$u"
	done
}

@test "reachability block is present and extractable" {
	run extract_block
	[ "$status" -eq 0 ]
	[[ "$output" == *"ipv4:"* ]]
	[[ "$output" == *"tcp listeners:"* ]]
}

# The guard for the bug that made the two "unavailable" tests below vacuous:
# with neither tool stubbed, BOTH must report unavailable. If anything ever puts
# a directory holding the host's iproute2 back on the block's PATH, this fails
# immediately and says so, instead of the negative cases quietly passing on the
# hosts that lack it and failing on the ones that don't.
@test "with neither tool stubbed, the block finds no ip(8) and no ss(8)" {
	# Positive control first: a PATH that resolves nothing at all would make
	# every `command -v` fail and satisfy the two assertions below for the wrong
	# reason, the same vacuous pass in mirror image. Proving a planted utility
	# IS found makes the absences below a real negative.
	PATH="$STUBS" "$BASH_BIN" -c 'command -v tr' >/dev/null

	run run_block "$STUBS"
	[ "$status" -eq 0 ]
	[[ "$output" == *"ip(8) unavailable"* ]]
	[[ "$output" == *"ss(8) unavailable"* ]]
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

	run run_block "$STUBS"
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

	run run_block "$STUBS"
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

	run run_block "$STUBS"
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
