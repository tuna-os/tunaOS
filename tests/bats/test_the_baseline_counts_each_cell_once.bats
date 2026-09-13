#!/usr/bin/env bats
# A sweep of 51 cells must not report 102.
#
# Each cell artifact ships result.json twice — once at its root, once inside
# the evidence bundle at evidence/<variant>/<flavor>/amd64/result.json. The
# collate step globbed `find results -name result.json`, took both, and every
# published total came out doubled: "DESKTOP CONTRACT BASELINE: 72/102 pass"
# for a 51-cell sweep, and 80/102 in run 34760268149 whose artifact is where
# this was caught.
#
# The reconciliation cannot catch it. It checks pass+fail+miss+err+lost ==
# total, and doubling both sides still balances — 102 == 102 held while every
# number in the table was twice its true value. So the duplicate has to be
# asserted directly, which is what these tests pin.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SWEEP="${REPO_ROOT}/.github/workflows/desktop-contract-sweep.yml"

_collate() {
	# The Build-the-baseline-table step, comments and all.
	sed -n '/name: Build the baseline table/,/name: Desktop completeness gate/p' "$SWEEP"
}

@test "the collate step exists to be tested" {
	# tunaOS#1730: a sed range that selects nothing passes every grep below.
	[ "$(_collate | wc -l)" -gt 20 ]
}

@test "the evidence copy of result.json is excluded from the tally" {
	_collate | grep -qF -- "-not -path '*/evidence/*'"
}

@test "the evidence copy is still uploaded, just not counted twice" {
	# The bundle is the point of #2495; this fix must not quietly drop it.
	grep -qF 'evidence/${{ matrix.variant }}/${{ matrix.desktop }}/amd64/' "$SWEEP"
}

@test "a cell reported more than once fails the step outright" {
	# The assertion the arithmetic could not make.
	_collate | grep -qF 'group_by(.cell)[] | select(length > 1)'
	_collate | grep -qF 'the same cell reported more than once'
}

@test "the duplicate check actually detects a duplicate" {
	# Run the real jq expression against a table with one cell twice.
	local found
	found="$(mktemp)"
	cat > "$found" <<-'JSON'
		[{"cell":"wahoo:gnome"},{"cell":"wahoo:gnome"},{"cell":"marlin:kde"}]
	JSON
	run jq -r 'group_by(.cell)[] | select(length > 1) | .[0].cell' "$found"
	[ "$status" -eq 0 ]
	[ "$output" = "wahoo:gnome" ]
	rm -f "$found"
}

@test "and stays silent on a table with no duplicate" {
	local found
	found="$(mktemp)"
	echo '[{"cell":"wahoo:gnome"},{"cell":"marlin:kde"}]' > "$found"
	run jq -r 'group_by(.cell)[] | select(length > 1) | .[0].cell' "$found"
	[ "$status" -eq 0 ]
	[ -z "$output" ]
	rm -f "$found"
}
