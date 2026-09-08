#!/usr/bin/env bats
# Failing gates must say where their evidence lives.
#
# WHY: an agent debugging this harness has to rediscover, every time, that the
# serial console goes to serial.log inside the output dir rather than stdout;
# that the SSH-based modes cannot work on published media because production
# images disable sshd; that the image ref is parsed from the ISO FILENAME, so a
# renamed download fails for an unrelated reason; and that the output dir holds
# screenshots and a boot-diagnostics dump nothing mentions. All four cost real
# time in one session. A gate that does not name its own evidence makes every
# consumer pay that again.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
E2E="${REPO_ROOT}/scripts/iso-e2e.sh"
RUNTIME="${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"

@test "iso-e2e prints agent instructions from the EXIT trap" {
  # From the trap, so all ~60 failure paths get it without each remembering.
  grep -q '_agent_debug_instructions' "$E2E"
  grep -q 'trap _on_exit EXIT' "$E2E"
}

@test "it stays silent on success" {
  # A gate that shouts on every green run trains people to ignore it.
  run bash -c "sed -n '/_agent_debug_instructions() {/,/^}/p' '$E2E'"
  [[ "$output" == *'[[ "$rc" -eq 0 ]] && return 0'* ]]
}

@test "it prints once, not once per subshell" {
  run bash -c "sed -n '/_agent_debug_instructions() {/,/^}/p' '$E2E'"
  [[ "$output" == *"_AGENT_HINT_PRINTED"* ]]
}

@test "cleanup still runs, and the exit code is preserved" {
  # The trap was cleanup_vm; wrapping it must not drop either behaviour, or a
  # failing gate starts reporting success and leaks QEMU on the runner.
  run bash -c "sed -n '/^_on_exit() {/,/^}/p' '$E2E'"
  [[ "$output" == *"cleanup_vm"* ]]
  [[ "$output" == *"local rc=\$?"* ]]
  [[ "$output" == *"return \"\$rc\""* ]]
}

@test "it names the artifacts an agent actually needs" {
  local body
  body="$(sed -n '/_agent_debug_instructions() {/,/^}/p' "$E2E")"
  for artifact in serial.log installed-serial.log current-phase.txt \
    boot-diagnostics.txt walkthrough ci-troubleshooting.md; do
    echo "$body" | grep -qF "$artifact" || {
      echo "missing pointer: $artifact"
      return 1
    }
  done
}

@test "it records the non-obvious facts that cost time" {
  local body
  body="$(sed -n '/_agent_debug_instructions() {/,/^}/p' "$E2E")"
  # sshd is the one that makes a published ISO look broken when it is fine.
  echo "$body" | grep -q 'disabled'
  echo "$body" | grep -q -- '--published'
  # The filename-derived image ref sent me probing ghcr.io/tuna-os/published.
  echo "$body" | grep -qi 'FILENAME'
}

@test "the in-guest checks point at their own evidence too" {
  # Serial is the only channel out of an installed system with no sshd, so
  # whatever these checks do not print is unknowable afterwards.
  grep -q 'AGENT:' "$RUNTIME"
  grep -q 'installed-serial.log' "$RUNTIME"
  grep -q 'ci-troubleshooting.md' "$RUNTIME"
}

@test "the guest hint only fires when something failed" {
  run bash -c "grep -B2 'AGENT: .* assertion(s) failed' '$RUNTIME'"
  [[ "$output" == *'if [[ "$FAIL" -gt 0 ]]'* ]]
}
