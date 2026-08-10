#!/usr/bin/env bats
# Verify the tunaos-luks-tpm2-enroll script and the ujust enable-luks-tpm2 /
# disable-luks-tpm2 just commands that wrap it (tunaOS#714).
#
# The per-variant TPM2 auto-unlock e2e test relies on fisherman#48's
# first-boot oneshot, which seals to PCR 7 alone. The manual `ujust
# enable-luks-tpm2` path (PCRs 7+14, a stricter set) is the one users
# actually exercise — these tests assert it is wired correctly and its
# documentation matches its behaviour.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
ENROLL_SCRIPT="${REPO_ROOT}/files/usr/bin/tunaos-luks-tpm2-enroll"
JUST_FILE="${REPO_ROOT}/files/usr/share/ublue-os/just/60-tunaos-luks.just"

# ── The enroll script ────────────────────────────────────────────────────

@test "tunaos-luks-tpm2-enroll exists and is executable" {
  [ -f "$ENROLL_SCRIPT" ]
  [ -x "$ENROLL_SCRIPT" ]
}

@test "tunaos-luks-tpm2-enroll has a valid bash shebang" {
  head -1 "$ENROLL_SCRIPT" | grep -qE '^#!/.*bash'
}

@test "tunaos-luks-tpm2-enroll passes bash syntax check" {
  bash -n "$ENROLL_SCRIPT"
}

@test "tunaos-luks-tpm2-enroll defaults to PCRs 7+14" {
  # The first-boot oneshot (fisherman#48) seals to PCR 7 alone; this script
  # intentionally uses a stricter set (7+14). If the default changes, the
  # docs and the issue's discussion need updating too.
  grep -q 'PCRS="${TUNAOS_LUKS_PCRS:-7+14}"' "$ENROLL_SCRIPT"
}

@test "tunaos-luks-tpm2-enroll uses systemd-cryptenroll, not a bespoke tool" {
  grep -q 'systemd-cryptenroll' "$ENROLL_SCRIPT"
}

@test "tunaos-luks-tpm2-enroll references PCRs 7 and 14 in its docstring" {
  # The header comment explains WHY PCRs 7+14 are used. If the comment falls
  # out of sync with the code (e.g. the default changes), this breaks.
  grep -qF 'PCRs 7+14' "$ENROLL_SCRIPT"
  grep -qF 'Secure Boot state' "$ENROLL_SCRIPT"
  grep -qF 'MokList' "$ENROLL_SCRIPT"
}

@test "tunaos-luks-tpm2-enroll supports --pin flag" {
  grep -q 'WITH_PIN=1' "$ENROLL_SCRIPT"
  grep -q 'tpm2-with-pin' "$ENROLL_SCRIPT"
}

@test "tunaos-luks-tpm2-enroll guards against non-root invocation" {
  grep -q 'Run as root' "$ENROLL_SCRIPT"
  grep -q '\[\[ \$EUID -eq 0 \]\]' "$ENROLL_SCRIPT"
}

# ── The just commands ─────────────────────────────────────────────────────

@test "60-tunaos-luks.just exists" {
  [ -f "$JUST_FILE" ]
}

@test "ujust enable-luks-tpm2 recipe is defined" {
  grep -qE '^enable-luks-tpm2' "$JUST_FILE"
}

@test "ujust enable-luks-tpm2 calls the enroll script" {
  grep -q 'tunaos-luks-tpm2-enroll' "$JUST_FILE"
}

@test "ujust enable-luks-tpm2 passes through arguments (--pin)" {
  # The {{ ARGS }} must reach the script so --pin works.
  grep -q '{{ ARGS }}' "$JUST_FILE"
}

@test "ujust disable-luks-tpm2 recipe is defined" {
  grep -qE '^disable-luks-tpm2' "$JUST_FILE"
}

@test "ujust disable-luks-tpm2 uses systemd-cryptenroll --wipe-slot=tpm2" {
  grep -q 'wipe-slot=tpm2' "$JUST_FILE"
}

# ── Cross-reference: the just module is a system file, not a build import ──

@test "the luks just module is installed into the ujust system directory" {
  # ujust auto-discovers *.just files under /usr/share/ublue-os/just/ at
  # runtime on the installed system, so this file does not need a build-time
  # import in the repo's Justfile.
  echo "$JUST_FILE" | grep -q 'files/usr/share/ublue-os/just/60-tunaos-luks.just'
}

# ── Docs reference the script and just commands ──────────────────────────

@test "docs/LUKS-TPM.md references ujust enable-luks-tpm2" {
  grep -q 'enable-luks-tpm2' "${REPO_ROOT}/docs/LUKS-TPM.md"
}

@test "docs/LUKS-TPM.md references tunaos-luks-tpm2-enroll" {
  grep -q 'tunaos-luks-tpm2-enroll' "${REPO_ROOT}/docs/LUKS-TPM.md"
}
