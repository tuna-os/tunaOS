#!/usr/bin/env bats
# shellcheck disable=SC1090  # SCRIPT path is resolved at runtime
# Unit tests for .github/scripts/cosign-retry.sh
#
# cosign-retry.sh is a sourced shell library (not an executable) that gates
# EVERY cosign sign/attest invocation in the release pipeline (see
# reusable-build-image.yml, rerun-infra-failures.yml). Its job is to retry
# only when the failure is a Sigstore availability blip and to fail fast on
# anything real — the 08-14/08-15 albacore incident (run 31858324517) burned
# six attempts on `cosign attest` during a Rekor 502 and skipped every one of
# the variant's twelve Promote jobs.
#
# These tests cover the pure logic: the transient-error classifier
# (_cosign_transient) and the deadline/backoff retry loop (cosign_retry),
# with `sleep` stubbed out so the suite runs in milliseconds.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/.github/scripts/cosign-retry.sh"

setup() {
  # Isolate a stub dir and stub `sleep` (records its argument to sleep.log)
  # so retry loops are instant and their backoff sequence is assertable.
  STUB_DIR="$(mktemp -d)"
  export PATH="${STUB_DIR}:${PATH}"
  cat > "${STUB_DIR}/sleep" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$1" >> "${STUB_DIR}/sleep.log"
exit 0
EOF
  chmod +x "${STUB_DIR}/sleep"
  : > "${STUB_DIR}/sleep.log"
  : > "${STUB_DIR}/count"

  # Load the library under test (defaults apply only when unset).
  source "$SCRIPT"
}

teardown() {
  rm -rf "$STUB_DIR"
}

# make_cmd <failures-before-success> <stderr-text> — a fake command that
# fails (exit 3) the first N invocations with the given stderr, then echoes
# a success line. Every invocation appends to the shared count file.
make_cmd() {
  local failures="$1" text="$2"
  local cmd="${STUB_DIR}/fake_cmd"
  cat > "$cmd" <<EOF
#!/usr/bin/env bash
count="\$(cat "${STUB_DIR}/count" 2>/dev/null || echo 0)"
count=\$((count + 1))
printf '%s\n' "\$count" > "${STUB_DIR}/count"
if [ "\$count" -le $failures ]; then
  echo "$text" >&2
  exit 3
fi
echo "fake success output"
EOF
  chmod +x "$cmd"
  echo "$cmd"
}

# ── sourcing ─────────────────────────────────────────────────────────────────

@test "sources cleanly and defines both functions" {
  [ "$(type -t cosign_retry)" = "function" ]
  [ "$(type -t _cosign_transient)" = "function" ]
}

@test "defaults: 40-minute deadline, 120s backoff cap" {
  unset SIGN_DEADLINE_MINUTES SIGN_BACKOFF_CAP_SECONDS
  source "$SCRIPT"
  [ "$SIGN_DEADLINE_MINUTES" = "40" ]
  [ "$SIGN_BACKOFF_CAP_SECONDS" = "120" ]
}

@test "respects env-provided deadline and cap" {
  unset SIGN_DEADLINE_MINUTES SIGN_BACKOFF_CAP_SECONDS
  export SIGN_DEADLINE_MINUTES=7 SIGN_BACKOFF_CAP_SECONDS=9
  source "$SCRIPT"
  [ "$SIGN_DEADLINE_MINUTES" = "7" ]
  [ "$SIGN_BACKOFF_CAP_SECONDS" = "9" ]
  unset SIGN_DEADLINE_MINUTES SIGN_BACKOFF_CAP_SECONDS
}

# ── _cosign_transient ────────────────────────────────────────────────────────

@test "_cosign_transient: rekor 502 is transient" {
  printf 'Error: GET https://rekor.sigstore.dev: status 502\n' > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -eq 0 ]
}

@test "_cosign_transient: rekor Bad Gateway is transient" {
  printf 'reading manifest: Bad Gateway from rekor.sigstore.dev\n' > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -eq 0 ]
}

@test "_cosign_transient: fulcio connection refused is transient" {
  printf 'dial tcp: connection refused fulcio.sigstore.dev\n' > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -eq 0 ]
}

@test "_cosign_transient: tuf-repo-cdn context deadline exceeded is transient" {
  printf 'context deadline exceeded (tuf-repo-cdn.sigstore.dev)\n' > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -eq 0 ]
}

@test "_cosign_transient: status matches case-insensitively" {
  printf 'REKOR.SIGSTORE.DEV returned Gateway Timeout\n' > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -eq 0 ]
}

@test "_cosign_transient: rekor 404 is NOT transient (real error)" {
  printf 'Error: status 404 from rekor.sigstore.dev\n' > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -ne 0 ]
}

@test "_cosign_transient: non-sigstore endpoint with 500 is NOT transient" {
  printf 'Error: registry.example.com returned status 500\n' > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -ne 0 ]
}

@test "_cosign_transient: sigstore name without outage status is NOT transient" {
  printf 'Error: signature mismatch verified against rekor.sigstore.dev\n' > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -ne 0 ]
}

@test "_cosign_transient: empty output is NOT transient" {
  : > "${STUB_DIR}/out"
  run _cosign_transient "${STUB_DIR}/out"
  [ "$status" -ne 0 ]
}

# ── cosign_retry ─────────────────────────────────────────────────────────────

@test "cosign_retry: success on first attempt passes stdout through, no sleep" {
  local ok="${STUB_DIR}/ok_cmd"
  printf '#!/usr/bin/env bash\necho "signed blob ok"\n' > "$ok"
  chmod +x "$ok"
  run cosign_retry "$ok"
  [ "$status" -eq 0 ]
  [[ "$output" == *"signed blob ok"* ]]
  [ ! -s "${STUB_DIR}/sleep.log" ]
}

@test "cosign_retry: transient failure retries (sleep 15s) then succeeds" {
  local cmd
  cmd="$(make_cmd 1 "Error: GET https://rekor.sigstore.dev: status 502")"
  run cosign_retry "$cmd"
  [ "$status" -eq 0 ]
  [[ "$output" == *"fake success output"* ]]
  [[ "$(cat "${STUB_DIR}/sleep.log")" == "15" ]]
}

@test "cosign_retry: backoff doubles and caps at SIGN_BACKOFF_CAP_SECONDS" {
  SIGN_BACKOFF_CAP_SECONDS=120
  local cmd
  cmd="$(make_cmd 4 "rekor.sigstore.dev status 502")"
  run cosign_retry "$cmd"
  [ "$status" -eq 0 ]
  # failures 1-4 sleep 15, 30, 60, 120; attempt 5 succeeds
  diff <(printf '15\n30\n60\n120\n') "${STUB_DIR}/sleep.log"
}

@test "cosign_retry: non-transient error fails immediately with the command's rc" {
  local bad="${STUB_DIR}/bad_cmd"
  printf '#!/usr/bin/env bash\necho "Error: invalid --certificate-identity" >&2\nexit 7\n' > "$bad"
  chmod +x "$bad"
  run cosign_retry "$bad"
  [ "$status" -eq 7 ]
  [ ! -s "${STUB_DIR}/sleep.log" ]
  [[ "$output" == *"non-transient"* ]]
  [[ "$output" != *"SIGSTORE_OUTAGE"* ]]
}

@test "cosign_retry: past the deadline emits SIGSTORE_OUTAGE and returns the command's rc" {
  SIGN_DEADLINE_MINUTES=0
  local cmd
  cmd="$(make_cmd 99 "rekor.sigstore.dev status 502")"
  run cosign_retry "$cmd"
  [ "$status" -eq 3 ]
  [[ "$output" == *"SIGSTORE_OUTAGE"* ]]
  [ ! -s "${STUB_DIR}/sleep.log" ]
}
