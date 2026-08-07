#!/usr/bin/env bats
# The fisherman install timeout, and what it says when it fires.
#
# bonito:kde is 9.1 GB in 64 layers. `bootc install to-filesystem` wrote it
# into an encrypted xfs volume inside a nested QEMU guest for 25 minutes,
# was still going, and the 1800s timer killed it. The harness then reported
#
#   ERROR: fisherman install timed out after 1800s (likely a stalled podman pull)
#
# There was no pull — the source is containers-storage:, and the comment three
# lines above the message says so. A diagnosis the code has not made is worse
# than none: it sent the investigation after a network problem that could not
# have existed.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/iso-e2e.sh"

_code() { grep -v '^[[:space:]]*#' "$SCRIPT"; }

@test "iso-e2e.sh: the install timeout is overridable and not hardcoded" {
  local code
  code="$(_code)"
  grep -qF 'TUNAOS_E2E_INSTALL_TIMEOUT' <<<"$code"
  # The literal must be gone from the timeout call itself.
  run grep -c 'timeout 1800 .*fisherman' <<<"$code"
  [ "$output" -eq 0 ]
}

@test "iso-e2e.sh: the timeout message does not assert a cause it has not checked" {
  # Strip comments: the paragraph explaining the old message quotes it.
  local code
  code="$(_code)"
  run grep -c 'stalled podman pull' <<<"$code"
  [ "$output" -eq 0 ]
}

@test "iso-e2e.sh: the timeout message prints the guest's own last progress line" {
  # Distinguishing "too slow" from "stalled" needs evidence, and fisherman
  # already emits it as JSON step/substep lines into the serial log.
  local blk
  blk="$(sed -n '/fisherman install timed out/,/return 3/p' "$SCRIPT")"
  [ -n "$blk" ]
  grep -qF 'SERIAL_LOG' <<<"$blk"
  grep -qE 'step|substep' <<<"$blk"
}
