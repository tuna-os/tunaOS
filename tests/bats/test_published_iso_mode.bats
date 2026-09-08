#!/usr/bin/env bats
# The one mode that can test media a user actually downloads.
#
# WHY: production ISOs ship sshd disabled (40-services.sh disables it unless
# ENABLE_SSHD=1), and every other mode in iso-e2e.sh reaches into the guest
# over SSH. MEASURED against the published marlin-kde ISO: `--luks` fails at
# "SSH not available", and an --ssh-only probe returns NO_SSH after 60 attempts.
# So the LUKS gate, the smoke checks and the installer GUI checks have only
# ever run against DEV ISOs — never against the artifact people download.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/iso-e2e.sh"

@test "the published mode exists and is documented in usage" {
  grep -q '\-\-published)' "$SCRIPT"
  grep -q 'MODE="published"' "$SCRIPT"
  grep -q '\-\-published\]' "$SCRIPT"
}

@test "the published mode never calls SSH" {
  # Extract the mode body and assert no SSH helper appears in it. A single
  # check_ssh here would reintroduce exactly the dependency this mode exists
  # to avoid, and would only be discovered against real published media.
  local body
  body="$(sed -n '/^published)$/,/^ssh)$/p' "$SCRIPT")"
  [ -n "$body" ]
  ! echo "$body" | grep -qE 'check_ssh|ssh_cmd|GUEST_SSH|sshpass|scp_cmd'
}

@test "readiness is judged by pixels, not the serial marker" {
  # Production media need not ship tunaos-live-ready.service. Waiting on the
  # marker there burns the full --timeout and reads as a hang; the first
  # attempt at this did exactly that for 900s.
  local body
  body="$(sed -n '/^published)$/,/^ssh)$/p' "$SCRIPT")"
  echo "$body" | grep -q 'wait_for_paint'
  ! echo "$body" | grep -q 'wait_for_ready'
}

@test "it drives the installer through the QEMU monitor" {
  local body
  body="$(sed -n '/^published)$/,/^ssh)$/p' "$SCRIPT")"
  echo "$body" | grep -q 'installer-walkthrough.py'
  echo "$body" | grep -q 'MONITOR_SOCK'
}

@test "a walkthrough failure is reported separately from a boot failure" {
  # A published ISO whose desktop is fine but whose installer regressed is a
  # different verdict from one that never booted. Non-fatal by default,
  # promotable with TUNAOS_PUBLISHED_STRICT=1.
  local body
  body="$(sed -n '/^published)$/,/^ssh)$/p' "$SCRIPT")"
  echo "$body" | grep -q 'TUNAOS_PUBLISHED_STRICT'
  echo "$body" | grep -q 'never painted'
}

@test "the walkthrough driver it depends on exists and takes a monitor socket" {
  local wt="${REPO_ROOT}/scripts/installer-walkthrough.py"
  [ -f "$wt" ]
  grep -q 'mon_path = args\[0\]' "$wt"
}

@test "readiness waits past the bootloader, not just for any paint" {
  # MEASURED on the published gurnard-pantheon ISO: wait_for_paint accepted the
  # GRUB menu as "painted" (it is non-blank), so the walkthrough drove sendkey
  # into a machine that was still booting and reported a blank, unchanging
  # screen — a false failure manufactured by the gate itself. The 10-ready
  # frame OCR'd to "gurnard-pantheon (live) / Reboot Into Firmware Interface /
  # Boot in 1s."
  local body
  body="$(sed -n '/^published)$/,/^ssh)$/p' "$SCRIPT")"
  echo "$body" | grep -q 'boot_menu_re'
  echo "$body" | grep -q 'Reboot Into Firmware'
  echo "$body" | grep -q 'GNU GRUB'
}

@test "a slow boot is still driven, not abandoned" {
  # The settle loop is bounded and non-fatal: a machine that takes longer than
  # the cap should still be handed to the walkthrough and judged there, rather
  # than failing here on a timer.
  local body
  body="$(sed -n '/^published)$/,/^ssh)$/p' "$SCRIPT")"
  echo "$body" | grep -q 'TUNAOS_PUBLISHED_BOOT_SETTLE'
  # The loop must break out, not exit.
  echo "$body" | grep -A12 'boot_menu_re' | grep -q 'break'
}

@test "a black screen is not mistaken for a booted session" {
  # The first settle loop broke out as soon as the frame had no bootloader
  # text — but a BLANK frame has no text either, so the moment the screen went
  # black between GRUB and the compositor it declared ready and handed the
  # walkthrough a black screen. MEASURED on gurnard-pantheon: 10-ready came
  # back stddev=0 after the settle "succeeded".
  local body
  body="$(sed -n '/^published)$/,/^ssh)$/p' "$SCRIPT")"
  echo "$body" | grep -q 'standard_deviation'
  # Must require non-blank AND not-bootloader, not either one alone.
  echo "$body" | grep -q 'frame_sd'
}
