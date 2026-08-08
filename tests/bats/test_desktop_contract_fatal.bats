#!/usr/bin/env bats
# The installed-boot desktop contract is a GATE, not a note.
#
# It shipped recording `fatal=0` with an explicit rule for its own promotion:
# "This is the first time the assertion has ever run post-install on any
# edition, so a red result would be ambiguous between 'the desktop does not
# come up' and 'the harvest is wrong'. Get one named run first, then gate on
# it." That run now exists twice — gurnard:pantheon (31232163933) and
# grouper:xfce (31232166865), both desktop_contract=ok — and the harvest was
# proven by its failures in the same arc: it reported dm_inactive with the
# DM's own journal tail while lightdm was genuinely crash-looping (#1073),
# then flipped to ok once the missing X server landed (#1086).
#
# These pin the promotion, its exit code, its escape hatch, and — the part
# that matters most — that it is checked where it can still catch what the
# pixel gate cannot.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
E2E="${REPO_ROOT}/scripts/iso-e2e.sh"

@test "the contract evidence line is recorded fatal=1" {
  run grep -F 'TUNAOS_LUKS_E2E_DESKTOP_CONTRACT desktop_contract=${_dc} fatal=1' "$E2E"
  [ "$status" -eq 0 ]
}

@test "no fatal=0 desktop-contract evidence line survives" {
  run grep -F 'TUNAOS_LUKS_E2E_DESKTOP_CONTRACT desktop_contract=${_dc} fatal=0' "$E2E"
  [ "$status" -ne 0 ]
}

@test "a non-ok contract returns 7" {
  run bash -c "grep -A10 'if \[\[ \"\\\$_dc\" != \"ok\" \]\]' '$E2E'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"return 7"* ]]
}

@test "exit code 7 is documented and distinguished from 6" {
  grep -qE '^#   7  desktop contract failed' "$E2E"
  # The table must say why it is not simply folded into 6.
  run grep -A6 '^#   7  desktop contract failed' "$E2E"
  [[ "$output" == *"greeter"* ]]
}

@test "the gate has an escape hatch, like the pixel gate" {
  grep -qF 'TUNAOS_DESKTOP_CONTRACT:-1' "$E2E"
  grep -qF 'TUNAOS_DESKTOP_CONTRACT=0' "$E2E"
}

@test "the contract is checked AFTER the pixel gate, not before" {
  # Two reasons, both load-bearing: every run keeps both evidence lines, and
  # a greeter that draws passes the pixel gate while failing the contract —
  # that case only reaches the contract check if it sits downstream.
  local pixel_at contract_at
  pixel_at="$(grep -n 'pixel_gate "\$_shot"' "$E2E" | head -1 | cut -d: -f1)"
  contract_at="$(grep -n 'if \[\[ "\$_dc" != "ok" \]\]' "$E2E" | head -1 | cut -d: -f1)"
  [ -n "$pixel_at" ]
  [ -n "$contract_at" ]
  [ "$pixel_at" -lt "$contract_at" ]
}

@test "the contract verdict is still computed before both consumers" {
  local dc_at pixel_at
  dc_at="$(grep -n 'record_luks_evidence "TUNAOS_LUKS_E2E_DESKTOP_CONTRACT' "$E2E" | head -1 | cut -d: -f1)"
  pixel_at="$(grep -n 'pixel_gate "\$_shot"' "$E2E" | head -1 | cut -d: -f1)"
  [ "$dc_at" -lt "$pixel_at" ]
}

@test "the workflow's exact-match PASS line is untouched" {
  # The LUKS workflow greps `grep -qx 'TUNAOS_LUKS_E2E_PASS encrypted=1
  # passphrase_unlock=1 installed_boot=1'` -- anchored and exact. Appending a
  # field to THAT line would turn every currently-green passphrase cell red
  # on a string mismatch, which is precisely why the contract got its own
  # evidence line instead. (The TPM-path PASS lines legitimately carry
  # tpm_unlock/desktop_contract fields; they are gated differently and are
  # not what this pins.)
  run grep -c 'TUNAOS_LUKS_E2E_PASS encrypted=1 passphrase_unlock=1 installed_boot=1"' "$E2E"
  [ "$output" -ge 1 ]
  # Nothing may follow installed_boot=1 on a passphrase PASS line.
  run grep 'TUNAOS_LUKS_E2E_PASS encrypted=1 passphrase_unlock=1' "$E2E"
  [[ "$output" != *'installed_boot=1 '* ]]
}

@test "a passing contract still reaches the success path" {
  # The flip must not make ok fall through to a failure return.
  run bash -c "awk '/if \[\[ \"\\\$_dc\" != \"ok\" \]\]/,/^\t\tfi\$/' '$E2E' | tail -3"
  [ "$status" -eq 0 ]
  [[ "$output" != *"return 0"* ]]
  run grep -F 'echo "==> LUKS passphrase gate PASSED' "$E2E"
  [ "$status" -eq 0 ]
}
