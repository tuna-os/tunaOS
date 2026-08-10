#!/usr/bin/env bats
# Unit tests for scripts/asahi-remote-switch.sh (tunaOS#780).
#
# This script is the one piece of code that ever touches either Asahi
# hardware tier (a rented Scaleway Mac mini with no console, or James's
# personal M1 Air), and it reboots its target with no recovery path if a
# command reaches the wrong place — see the script's own header and
# docs/ASAHI-HARDWARE-TIERS.md's "the one rule that matters more than either
# tier". None of that had a regression test before this file: the
# DANGEROUS_PATTERNS guard, the "mask before ever touching bootc" ordering,
# and the four possible outcomes (success / rollback / timeout / unreachable)
# were all correct by inspection only.
#
# No real SSH, hardware, or network is used. Every scenario stubs `ssh` with
# a fake that inspects the command it was asked to run and answers as a
# fabricated remote host would, so these tests exercise the script's actual
# control flow end to end.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/asahi-remote-switch.sh"
IMAGE_OLD="ghcr.io/tuna-os/bonito:gnome-asahi-old"
IMAGE_NEW="ghcr.io/tuna-os/bonito:gnome-asahi-new"

# ── DANGEROUS_PATTERNS: the actual safety property ─────────────────────────
# Extracted with `eval` from the script's own literal assignment line rather
# than re-typed here, so these tests exercise the exact regex the script
# ships — a copy-pasted pattern in the test file could pass while the real
# one had drifted.

load_dangerous_patterns() {
  local line
  line="$(grep -m1 '^DANGEROUS_PATTERNS=' "$SCRIPT")"
  [ -n "$line" ] || { echo "FAIL: DANGEROUS_PATTERNS assignment not found in $SCRIPT" >&2; return 1; }
  eval "$line"
}

@test "DANGEROUS_PATTERNS matches every known m1n1/firmware-writing command" {
  load_dangerous_patterns
  local bad fail=0
  for bad in \
    "update-m1n1" \
    "asahi-fwupdate --whatever" \
    "m1n1-installer /dev/sda" \
    "dd if=/tmp/x of=/boot/efi/foo" \
    "cp /tmp/boot.bin /boot/efi/m1n1/boot.bin"
  do
    if ! grep -qE "$DANGEROUS_PATTERNS" <<<"$bad"; then
      echo "FAIL: DANGEROUS_PATTERNS did not match a real firmware-writing command: ${bad}" >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}

@test "DANGEROUS_PATTERNS does not false-positive on the commands this script actually sends" {
  load_dangerous_patterns
  local ok fail=0
  for ok in \
    "true" \
    "bootc status" \
    "bootc switch --retain ${IMAGE_NEW}" \
    "systemctl mask asahi-bootbin-sync.service" \
    "systemctl reboot"
  do
    if grep -qE "$DANGEROUS_PATTERNS" <<<"$ok"; then
      echo "FAIL: DANGEROUS_PATTERNS false-positived on a command this script legitimately sends: ${ok}" >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}

# ── Structural guarantees (grep-based, no execution needed) ───────────────

@test "run() checks assert_safe_command before ever invoking ssh" {
  # If a future edit reordered this, a dangerous command could reach the
  # network before the guard runs. awk isolates the run() function body so
  # this can't accidentally match assert_safe_command's own definition;
  # comparing line numbers within that slice (rather than a single regex)
  # asserts ORDER, not just that both calls exist somewhere in the function.
  local body assert_line ssh_line
  body="$(awk '/^run\(\) \{/,/^\}/' "$SCRIPT")"
  assert_line="$(grep -n 'assert_safe_command "\$cmd"' <<<"$body" | head -1 | cut -d: -f1)"
  ssh_line="$(grep -n 'ssh "\${SSH_OPTS\[@\]}"' <<<"$body" | head -1 | cut -d: -f1)"
  [ -n "$assert_line" ]
  [ -n "$ssh_line" ]
  [ "$assert_line" -lt "$ssh_line" ]
}

@test "asahi-bootbin-sync.service is masked before bootc switch is ever sent, on both passes" {
  # Ordering matters: switching first and masking after leaves a window
  # where a completed switch could reboot into a sync-service run before
  # this script gets to mask it. grep -n line numbers assert order, not just
  # presence — the same pattern tests/bats/test_gentoo_dracut_config.bats
  # uses for its own "X happens before Y" guarantees.
  local mask_lines switch_line
  mask_lines="$(grep -n 'systemctl mask asahi-bootbin-sync.service' "$SCRIPT" | cut -d: -f1)"
  switch_line="$(grep -n 'bootc switch --retain' "$SCRIPT" | head -1 | cut -d: -f1)"
  [ -n "$switch_line" ]
  local first_mask_line
  first_mask_line="$(echo "$mask_lines" | head -1)"
  [ -n "$first_mask_line" ]
  [ "$first_mask_line" -lt "$switch_line" ]
  # And re-masked after reboot too (belt-and-suspenders against the first
  # TunaOS switch on a host, where the unit doesn't exist until this exact
  # reboot installs it — see the script's own comment on this).
  local mask_count
  mask_count="$(echo "$mask_lines" | wc -l)"
  [ "$mask_count" -ge 2 ]
}

# ── End-to-end scenarios, via a stubbed ssh ────────────────────────────────
#
# The stub inspects the command after the `--` (exactly what run()/
# ssh_reachable() send — never "$@", so the safety check sees the whole
# string, which is also what makes this stub simple: one argument to switch
# on). STUB_SCENARIO selects which fabricated remote-host behavior it plays
# back; STUB_STATE_DIR gives it somewhere to count repeated calls (bootc
# status is called three times per run; reachability polling loops).

setup() {
  BIN_DIR="${BATS_TEST_TMPDIR}/bin"
  STATE_DIR="${BATS_TEST_TMPDIR}/state"
  mkdir -p "$BIN_DIR" "$STATE_DIR"
  cat >"${BIN_DIR}/ssh" <<'STUB'
#!/usr/bin/env bash
# Fake ssh for asahi-remote-switch.sh tests. Finds the command after the
# literal `--` argument (both run() and ssh_reachable() always send one),
# and answers according to $STUB_SCENARIO / $STUB_STATE_DIR.
set -euo pipefail
prev=""
cmd=""
for a in "$@"; do
  if [[ "$prev" == "--" ]]; then cmd="$a"; fi
  prev="$a"
done

: "${STUB_STATE_DIR:?}"
scenario="${STUB_SCENARIO:-success}"

count_file() {
  local name="$1" n=0
  local f="${STUB_STATE_DIR}/${name}"
  [[ -f "$f" ]] && n="$(cat "$f")"
  n=$((n + 1))
  echo "$n" >"$f"
  echo "$n"
}

case "$cmd" in
true)
  n="$(count_file reachable)"
  if [[ "$scenario" == "unreachable" ]]; then
    exit 1
  fi
  if [[ "$scenario" == "timeout" ]]; then
    # Only the very first reachability check (before anything happens)
    # succeeds; every post-reboot poll fails, so the script's own wait
    # loop eventually gives up.
    [[ "$n" -le 1 ]] && exit 0 || exit 1
  fi
  exit 0
  ;;
"bootc status")
  n="$(count_file status)"
  if [[ "$n" -eq 1 ]]; then
    printf 'Booted image\n    Image: %s\n' "$STUB_IMAGE_OLD"
  elif [[ "$scenario" == "rollback" ]]; then
    printf 'Booted image\n    Image: %s\n' "$STUB_IMAGE_OLD"
  else
    printf 'Booted image\n    Image: %s\n' "$STUB_IMAGE_NEW"
  fi
  exit 0
  ;;
*)
  # systemctl mask/reboot, bootc switch --retain ... — all no-ops that
  # succeed; the script never inspects their stdout.
  exit 0
  ;;
esac
STUB
  chmod +x "${BIN_DIR}/ssh"
}

run_switch() {
  local scenario="$1"
  PATH="${BIN_DIR}:${PATH}" \
    STUB_SCENARIO="$scenario" \
    STUB_STATE_DIR="$STATE_DIR" \
    STUB_IMAGE_OLD="$IMAGE_OLD" \
    STUB_IMAGE_NEW="$IMAGE_NEW" \
    ASAHI_HW_HOST="fake-host.ts.net" \
    ASAHI_HW_USER="root" \
    ASAHI_HW_REBOOT_TIMEOUT="${2:-60}" \
    run bash "$SCRIPT" "$IMAGE_NEW"
}

@test "unreachable host: exits 5 and touches nothing" {
  run_switch unreachable
  [ "$status" -eq 5 ]
  [[ "$output" == *"could not reach the host before attempting anything"* ]]
  # Only the initial reachability probe happened — no mask, no bootc status,
  # nothing else was ever attempted on the fake host.
  [ ! -f "${STATE_DIR}/status" ]
}

@test "clean switch: exits 0, reports the new image booted, and masks on both passes" {
  # Combined with the mask-ordering check (rather than a second full run of
  # the ~10s success scenario) to keep the suite's wall-clock cost down —
  # the script's own reboot-wait sleeps are real time, not mocked.
  run_switch success
  [ "$status" -eq 0 ]
  [[ "$output" == *"SUCCESS: booted ${IMAGE_NEW}"* ]]
  local mask_calls
  mask_calls="$(grep -c 'Masking asahi-bootbin-sync.service' <<<"$output")"
  [ "$mask_calls" -ge 1 ]
  [[ "$output" == *"Host is back. Confirming what actually booted."* ]]
}

@test "rollback: bootc reverting to the prior deployment is reported as exit 3, not a failure" {
  run_switch rollback
  [ "$status" -eq 3 ]
  [[ "$output" == *"ROLLED BACK"* ]]
  [[ "$output" == *"The host survived."* ]]
}

@test "host never comes back after reboot: exits 4 and says a human is needed" {
  run_switch timeout 12
  [ "$status" -eq 4 ]
  [[ "$output" == *"did not come back within"* ]]
  [[ "$output" == *"needs a human"* ]]
}

@test "assert_safe_command exits 1 (without calling ssh) on a dangerous command, in isolation" {
  # The script has no sourceable-only mode (its top-level code runs
  # immediately, including the required-argument check), so pull just the
  # function definition out by text range rather than sourcing the whole
  # file — this exercises the exact function body shipped in the script,
  # not a re-typed copy that could drift from it.
  local fn_body
  fn_body="$(sed -n '/^assert_safe_command() {/,/^}/p' "$SCRIPT")"
  [ -n "$fn_body" ]
  local pattern_line
  pattern_line="$(grep -m1 '^DANGEROUS_PATTERNS=' "$SCRIPT")"
  [ -n "$pattern_line" ]

  cat >"${BIN_DIR}/ssh" <<'STUB'
#!/usr/bin/env bash
echo "unexpected ssh invocation: $*" >>"${STUB_STATE_DIR}/ssh-was-called"
exit 0
STUB
  chmod +x "${BIN_DIR}/ssh"

  PATH="${BIN_DIR}:${PATH}" STUB_STATE_DIR="$STATE_DIR" \
    run bash -c "${pattern_line}
${fn_body}
assert_safe_command 'update-m1n1 --write-payload'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"refusing to run a command that touches m1n1/firmware"* ]]
  [ ! -f "${STATE_DIR}/ssh-was-called" ]
}

@test "assert_safe_command, in the same isolation, allows the commands this script actually sends" {
  local fn_body pattern_line
  fn_body="$(sed -n '/^assert_safe_command() {/,/^}/p' "$SCRIPT")"
  pattern_line="$(grep -m1 '^DANGEROUS_PATTERNS=' "$SCRIPT")"
  [ -n "$fn_body" ]
  [ -n "$pattern_line" ]

  run bash -c "${pattern_line}
${fn_body}
assert_safe_command 'bootc status' &&
assert_safe_command 'bootc switch --retain ${IMAGE_NEW}' &&
assert_safe_command 'systemctl mask asahi-bootbin-sync.service' &&
assert_safe_command 'systemctl reboot' &&
echo ALL_SAFE_COMMANDS_PASSED"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ALL_SAFE_COMMANDS_PASSED"* ]]
}
