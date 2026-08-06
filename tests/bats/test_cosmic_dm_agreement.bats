#!/usr/bin/env bats
# Which display manager COSMIC uses is encoded in five places, and they have
# to agree or the image fails somewhere between build and boot:
#
#   1. configure-desktop-runtime.sh   which unit gets `systemctl enable`d
#   2. verify-desktop-experience.sh   dm_pattern, checked in the booted VM
#   3. manifests/desktops/cosmic.yaml which greeter is installed at all
#   4. e2e-runtime-checks.sh          the installed-system TAP DM assertion
#   5. scripts/boot-gate.sh           the local corral boot gate
#
# (4) and (5) assert the same fact as (2) against the same booted image, so a
# fix that only widens (2) leaves the gate emitting
# "not ok - display manager matches cosmic contract" as a ::warning:: — and a
# hard failure under E2E_SMOKE_STRICT=1 — for an image that is working.
#
# Adding cosmic-greeter to the Ubuntu package list broke (1) — its postinst
# claims display-manager.service, so enabling greetd failed the build. Fixing
# (1) to probe then broke (2), which still demanded greetd:
#
#   TUNAOS_DESKTOP_CONTRACT_FAIL reason=dm_mismatch
#     dm=cosmic-greeter.service expected=^greetd\.service$
#
# grouper:cosmic, run 31089333407 — a clean build and a booting VM, rejected at
# the last gate. Both greeters are legitimate: openSUSE packages no
# cosmic-greeter (sailfin runs greetd with gtkgreet+cage), while the Ubuntu PPA
# and the Fedora/EL10 repos all ship it. kde has had exactly this duality —
# sddm vs plasmalogin — handled in both places for a while; cosmic now matches.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
RUNTIME="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
CONTRACT="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"

# The cosmic case block of the contract script, so a change to niri's
# identical greetd-only pattern cannot satisfy these assertions.
cosmic_contract_block() {
  awk '/^cosmic\)$/{f=1} f{print} f&&/^\t;;$/{exit}' "$CONTRACT"
}

@test "the build-time DM choice accepts both greeters" {
  run grep -q 'dm=cosmic-greeter' "$RUNTIME"
  [ "$status" -eq 0 ]
  run grep -q 'dm=greetd' "$RUNTIME"
  [ "$status" -eq 0 ]
}

@test "the runtime contract accepts both greeters" {
  run bash -c "$(declare -f cosmic_contract_block); CONTRACT='$CONTRACT'; cosmic_contract_block"
  [ "$status" -eq 0 ]
  [[ "$output" == *'cosmic-greeter'* ]]
  [[ "$output" == *'greetd'* ]]
  # The old single-greeter pattern must be gone from THIS block.
  [[ "$output" != *"dm_pattern='^greetd\\.service\$'"* ]]
}

@test "niri still demands greetd alone" {
  # niri has no cosmic-greeter to fall back to, so widening its pattern would
  # be wrong rather than merely permissive. Guards against a careless
  # search-and-replace across the file.
  run bash -c "awk '/^niri\)\$/{f=1} f{print} f&&/^\t;;\$/{exit}' '$CONTRACT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"dm_pattern='^greetd\\.service\$'"* ]]
  [[ "$output" != *'cosmic-greeter'* ]]
}

@test "every section that installs cosmic-greeter can satisfy the contract" {
  # If a manifest ships cosmic-greeter, the contract must accept it — that is
  # the pairing this file exists to keep. Sections shipping only greetd are
  # equally fine; both are in the accepted pattern.
  run bash -c "grep -c 'cosmic-greeter' '${REPO_ROOT}/manifests/desktops/cosmic.yaml'"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
  run bash -c "$(declare -f cosmic_contract_block); CONTRACT='$CONTRACT'; cosmic_contract_block"
  [[ "$output" == *'cosmic-greeter'* ]]
}

# ── The two other assertions on the same booted image ─────────────────────

@test "the installed-system TAP checks accept both greeters" {
  # e2e-runtime-checks.sh runs from /usr/libexec in the booted VM alongside the
  # desktop contract, and iso-e2e.sh harvests its fail count off the serial
  # console. Its cosmic arm has to say what the contract says.
  run grep -E '^cosmic\) dm_pattern=' "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *cosmic-greeter* ]]
  [[ "$output" == *greetd* ]]
  # niri must not have been dragged along by the split.
  run grep -qE '^niri \| cosmic\)' "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"
  [ "$status" -ne 0 ]
  run grep -qE "^niri\) dm_pattern='\^greetd" "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"
  [ "$status" -eq 0 ]
}

@test "boot-gate.sh accepts both greeters for cosmic" {
  run grep -oE 'cosmic\*\) DM="[^"]*"' "${REPO_ROOT}/scripts/boot-gate.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *cosmic-greeter* ]]
  [[ "$output" == *greetd* ]]
}
