#!/usr/bin/env bats
# Behavioral tests for scripts/lib/pixel-gate.sh — the decision table that
# turns the already-captured screenshot/timelapse evidence into a verdict —
# plus wiring pins for how scripts/iso-e2e.sh consumes it.
#
# The gap this closes: the installed-boot fatal gates ended at
# "display-manager.service active", and a black console shipped under a
# green cell (run 29645108966) while 151-210 real timelapse frames and a
# stddev-measured screenshot sat unasserted in the artifacts.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
LIB="${REPO_ROOT}/scripts/lib/pixel-gate.sh"
E2E="${REPO_ROOT}/scripts/iso-e2e.sh"

gate() {
  # shellcheck disable=SC1090
  run bash -c "source '$LIB'; pixel_gate \"\$@\"" _ "$@"
}

# ── decision table ─────────────────────────────────────────────────────────

@test "drawn + frames captured = fatal pass" {
  gate drawn 0.18 172 0
  [ "$status" -eq 0 ]
  [[ "$output" == "TUNAOS_LUKS_E2E_PIXEL_GATE result=pass frames=172 stddev=0.18 fatal=1" ]]
}

@test "blank capture is a fatal failure carrying its measurement" {
  gate blank 0.0007 151 0
  [ "$status" -eq 1 ]
  [[ "$output" == *"result=blank"* ]]
  [[ "$output" == *"stddev=0.0007"* ]]
  [[ "$output" == *"fatal=1"* ]]
}

@test "no capture at all on a measurable host is a fatal failure" {
  gate absent "" 160 0
  [ "$status" -eq 1 ]
  [[ "$output" == *"result=absent"* ]]
  [[ "$output" == *"stddev=na"* ]]
}

@test "zero frames on a measurable host fails even when the still looks drawn" {
  # On the plain path the recorder shares the screenshot's monitor socket;
  # an install-long capture that produced nothing means the verification
  # channel itself never worked, and an unverifiable cell must not be green.
  gate drawn 0.2 0 0
  [ "$status" -eq 1 ]
  [[ "$output" == *"result=no_frames"* ]]
  gate drawn 0.2 "" 0
  [ "$status" -eq 1 ]
  [[ "$output" == *"result=no_frames"* ]]
}

@test "virgl hosts are named as skipped, never silently passed or failed" {
  # screendump has no surface under GL scanout — frames and captures measure
  # nothing there, whatever their values.
  gate absent "" "" 1
  [ "$status" -eq 0 ]
  [[ "$output" == *"result=skipped_virgl"* ]]
  [[ "$output" == *"fatal=0"* ]]
}

@test "a capture without ImageMagick to judge it stays advisory" {
  # Recording that refusal as blank would invent a product failure out of a
  # missing host package — iso-e2e.sh already refuses to; so does the gate.
  gate unmeasured "" 143 0
  [ "$status" -eq 0 ]
  [[ "$output" == *"result=unmeasured"* ]]
  [[ "$output" == *"fatal=0"* ]]
}

# ── wiring in iso-e2e.sh ───────────────────────────────────────────────────

@test "iso-e2e sources the gate lib and records its evidence line" {
  grep -qF '. "${SCRIPT_DIR}/lib/pixel-gate.sh"' "$E2E"
  grep -qF 'record_luks_evidence "$_pixel_line"' "$E2E"
}

@test "iso-e2e stops the timelapse before judging, so the frame count is real" {
  # The stop must happen in the gate path itself, not only in cleanup_vm's
  # EXIT trap — cleanup runs after the verdict.
  run grep -B3 'frame-count.txt' "$E2E"
  [[ "$output" == *'record-timelapse.sh" stop'* ]]
}

@test "a fatal gate verdict exits 6 and is documented, with an explicit escape hatch" {
  run grep -A6 'TUNAOS_PIXEL_GATE:-1' "$E2E"
  [[ "$output" == *"return 6"* ]]
  grep -qE '^#   6  pixel gate failed' "$E2E"
  grep -qF 'TUNAOS_PIXEL_GATE=0' "$E2E"
}

@test "the existing INSTALLED_SCREENSHOT evidence line is unchanged" {
  # The workflow greps are exact-match and anchored; the gate adds a NEW
  # line rather than mutating this one (see the comment above it in
  # iso-e2e.sh about why appending a field breaks every green cell).
  grep -qF 'TUNAOS_LUKS_E2E_INSTALLED_SCREENSHOT rendered=${_shot} stddev=${SCREENSHOT_STDDEV:-na} fatal=0' "$E2E"
}
