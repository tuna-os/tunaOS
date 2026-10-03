#!/usr/bin/env bats
# Unit tests for the visual-verification module extracted from iso-e2e.sh.
# These exercise the production functions without starting QEMU.

setup() {
	REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
	VISUAL_LIB="${REPO_ROOT}/scripts/lib/e2e-visual.sh"
	OUTPUT_DIR="${BATS_TEST_TMPDIR}/out"
	MONITOR_SOCK="${OUTPUT_DIR}/monitor.sock"
	SCRIPT_DIR="${REPO_ROOT}/scripts"
	mkdir -p "$OUTPUT_DIR"
	# shellcheck source=../../scripts/lib/e2e-visual.sh
	source "$VISUAL_LIB"
}

@test "iso-e2e delegates visual verification to the module" {
	local harness="${REPO_ROOT}/scripts/iso-e2e.sh"
	grep -q 'source=lib/e2e-visual.sh' "$harness"
	! grep -q '^screenshot()' "$harness"
	! grep -q '^screenshot_sane()' "$harness"
	! grep -q '^wait_for_paint()' "$harness"
}

@test "visual module exports its four-function interface" {
	run bash -c "source '$VISUAL_LIB'; type -t screenshot screenshot_compare screenshot_sane wait_for_paint"
	[ "$status" -eq 0 ]
	[ "$output" = $'function\nfunction\nfunction\nfunction' ]
}

@test "screenshot_sane prefers a VNC PNG and publishes its measurement" {
	mkdir -p "${BATS_TEST_TMPDIR}/bin"
	cat >"${BATS_TEST_TMPDIR}/bin/convert" <<'STUB'
#!/usr/bin/env bash
printf '%s' "$1" >"$CONVERT_INPUT"
printf '0.125'
STUB
	chmod +x "${BATS_TEST_TMPDIR}/bin/convert"
	printf 'png' >"${OUTPUT_DIR}/ready.png"
	printf 'ppm' >"${OUTPUT_DIR}/ready.ppm"
	export CONVERT_INPUT="${BATS_TEST_TMPDIR}/convert-input"

	PATH="${BATS_TEST_TMPDIR}/bin:${PATH}" run screenshot_sane ready
	[ "$status" -eq 0 ]
	[ "$(<"$CONVERT_INPUT")" = "${OUTPUT_DIR}/ready.png" ]
	[[ "$output" == *"stddev=0.125"* ]]
}

@test "screenshot_sane rejects a measured blank frame" {
	mkdir -p "${BATS_TEST_TMPDIR}/bin"
	cat >"${BATS_TEST_TMPDIR}/bin/convert" <<'STUB'
#!/usr/bin/env bash
printf '0.001'
STUB
	chmod +x "${BATS_TEST_TMPDIR}/bin/convert"
	printf 'ppm' >"${OUTPUT_DIR}/blank.ppm"

	PATH="${BATS_TEST_TMPDIR}/bin:${PATH}" run screenshot_sane blank
	[ "$status" -eq 1 ]
	[[ "$output" == *"looks blank"* ]]
}

@test "wait_for_paint retries capture until a frame is sane" {
	attempt_file="${BATS_TEST_TMPDIR}/attempts"
	printf '0' >"$attempt_file"
	screenshot() { printf 'capture=%s\n' "$1"; }
	screenshot_sane() {
		local attempt
		attempt=$(<"$attempt_file")
		attempt=$((attempt + 1))
		printf '%s' "$attempt" >"$attempt_file"
		SCREENSHOT_STDDEV="0.2"
		[[ "$attempt" -ge 2 ]]
	}
	sleep() { :; }
	TBOX_E2E_PAINT_TIMEOUT=5 run wait_for_paint ready
	[ "$status" -eq 0 ]
	[[ "$output" == *"painted on attempt 2"* ]]
	[ "$(<"$attempt_file")" -eq 2 ]
}
