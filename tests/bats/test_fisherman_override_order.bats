#!/usr/bin/env bats
# FISHERMAN_OVERRIDE has to be installed BEFORE run_install() checks whether
# the live image ships a fisherman.
#
# It used to be installed ~260 lines after that check. The check is a hard
# `return 3`, so on an image carrying no fisherman the run died without ever
# installing the binary the workflow had just built for it:
#
#   ERROR: fisherman not found on live image (VARIANT=guppy FLAVOR=xfce)
#   ERROR: and TBOX_E2E_IMAGE is unset, so the generic bootc path cannot name
#          an image ref
#
# guppy:xfce, LUKS run 31131624108 — 55 seconds into the LUKS step, after a
# 65-minute Gentoo build, with FISHERMAN_OVERRIDE=/tmp/fisherman-bin present
# on the runner and the workflow's own "Build fisherman in a golang container"
# step green immediately above it. All three guppy cells fail this way, and
# the wall-clock made it look like an install timeout rather than a 55-second
# abort.
#
# The ordering is the whole fix, and ordering is invisible to every other kind
# of check: both statements are individually correct, the script passes
# shellcheck and `bash -n` either way, and the failure only shows up against a
# live image that happens to lack the binary.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/iso-e2e.sh"

# Line number of the first non-comment line matching a pattern.
code_line() {
	grep -vn '^[[:space:]]*#' "$SCRIPT" | grep -m1 -- "$1" | cut -d: -f1
}

@test "the override and the presence check are both still present" {
	run sh -c "grep -c 'Overriding fisherman with' '$SCRIPT'"
	[ "$output" -eq 1 ]
	run sh -c "grep -c 'command -v /usr/local/bin/fisherman' '$SCRIPT'"
	[ "$output" -eq 1 ]
}

# The assertion this file exists for.
@test "the override is installed before the presence check" {
	local override check
	override=$(grep -n 'Overriding fisherman with' "$SCRIPT" | head -1 | cut -d: -f1)
	check=$(grep -n 'command -v /usr/local/bin/fisherman' "$SCRIPT" | head -1 | cut -d: -f1)
	[ -n "$override" ]
	[ -n "$check" ]
	if [ "$override" -ge "$check" ]; then
		echo "FAIL: FISHERMAN_OVERRIDE is installed at line ${override}, but the" >&2
		echo "      'is fisherman present' check at line ${check} returns 3 first." >&2
		echo "      On an image that ships no fisherman the override never runs," >&2
		echo "      which is the only case it exists for (guppy, run 31131624108)." >&2
		return 1
	fi
}

# Both must be inside run_install(), not split across functions — moving the
# override into a caller would satisfy the line-order test while changing when
# it runs relative to the ssh_cmd/scp_cmd locals it uses.
@test "both live inside run_install()" {
	local start end override check
	start=$(grep -n '^run_install() {' "$SCRIPT" | cut -d: -f1)
	[ -n "$start" ]
	# The next top-level function definition after run_install().
	end=$(grep -n '^[a-z_]*() {' "$SCRIPT" | awk -F: -v s="$start" '$1>s {print $1; exit}')
	[ -n "$end" ] || end=$(wc -l <"$SCRIPT")
	override=$(grep -n 'Overriding fisherman with' "$SCRIPT" | head -1 | cut -d: -f1)
	check=$(grep -n 'command -v /usr/local/bin/fisherman' "$SCRIPT" | head -1 | cut -d: -f1)
	[ "$override" -gt "$start" ] && [ "$override" -lt "$end" ]
	[ "$check" -gt "$start" ] && [ "$check" -lt "$end" ]
}

# The locals the override block uses are declared earlier in run_install().
# If someone moves the override above them it silently scps with an empty
# command array.
@test "ssh_cmd and scp_cmd are declared before the override uses them" {
	local decl override
	decl=$(grep -n 'local scp_cmd=(' "$SCRIPT" | awk -F: -v s="$(grep -n '^run_install() {' "$SCRIPT" | cut -d: -f1)" '$1>s {print $1; exit}')
	override=$(grep -n 'Overriding fisherman with' "$SCRIPT" | head -1 | cut -d: -f1)
	[ -n "$decl" ]
	[ "$decl" -lt "$override" ]
}

# The error path should say why an override that was set did not take, rather
# than reporting only "fisherman not found" — that message is what sent the
# first read of run 31131624108 chasing an install timeout.
@test "a set-but-absent override is called out in the failure" {
	run awk '/fisherman not found on live image/{f=1} f{print} f&&/return 3/{exit}' "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"FISHERMAN_OVERRIDE"* ]]
}
