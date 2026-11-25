#!/usr/bin/env bats
# /var/run must be a link to ../run (tunaOS#5005).

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/checks/fix-var-run.sh"

setup() {
	export TUNAOS_ROOT="${BATS_TEST_TMPDIR}/root"
	mkdir -p "${TUNAOS_ROOT}/var" "${TUNAOS_ROOT}/run"
}

@test "a /var/run directory becomes a link to ../run and its content moves" {
	mkdir -p "${TUNAOS_ROOT}/var/run/spice-vdagentd"
	run "${SCRIPT}"
	[ "$status" -eq 0 ]
	[ "$(readlink "${TUNAOS_ROOT}/var/run")" = "../run" ]
	[ -d "${TUNAOS_ROOT}/run/spice-vdagentd" ]
}

@test "a missing /var/run gets the link" {
	run "${SCRIPT}"
	[ "$status" -eq 0 ]
	[ "$(readlink "${TUNAOS_ROOT}/var/run")" = "../run" ]
}

@test "an existing link is left alone" {
	ln -s ../run "${TUNAOS_ROOT}/var/run"
	run "${SCRIPT}"
	[ "$status" -eq 0 ]
	[ "$(readlink "${TUNAOS_ROOT}/var/run")" = "../run" ]
}

@test "a link to another target fails the check" {
	ln -s ../elsewhere "${TUNAOS_ROOT}/var/run"
	run "${SCRIPT}"
	[ "$status" -ne 0 ]
}

@test "the base and desktop stages run it" {
	grep -qxF '/run/context/build_scripts/checks/fix-var-run.sh' "${REPO_ROOT}/build_scripts/99-cleanup.sh"
	grep -qxF '"$(dirname "${BASH_SOURCE[0]}")/../checks/fix-var-run.sh"' "${REPO_ROOT}/build_scripts/desktop/tuna-flatpak-remote.sh"
}
