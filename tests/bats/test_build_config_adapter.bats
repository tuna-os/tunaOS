#!/usr/bin/env bats

setup() {
	REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
}

@test "build config resolves independently of caller working directory" {
	run bash -c 'cd /tmp && source "$1/scripts/lib/build-config.sh" && tunaos_build_config' _ "$REPO_ROOT"
	[ "$status" -eq 0 ]
	[ "$output" = "${REPO_ROOT}/.github/build-config.yml" ]
}

@test "build config honors the compatibility override" {
	custom_config="${BATS_TEST_TMPDIR}/build-config.yml"
	touch "$custom_config"
	run env TUNAOS_BUILD_CONFIG="$custom_config" bash -c \
		'source "$1/scripts/lib/build-config.sh" && tunaos_build_config' _ "$REPO_ROOT"
	[ "$status" -eq 0 ]
	[ "$output" = "$custom_config" ]
}

@test "build config rejects a missing override" {
	missing_config="${BATS_TEST_TMPDIR}/missing.yml"
	run env TUNAOS_BUILD_CONFIG="$missing_config" bash -c \
		'source "$1/scripts/lib/build-config.sh" && tunaos_build_config' _ "$REPO_ROOT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"build config not found: ${missing_config}"* ]]
}
