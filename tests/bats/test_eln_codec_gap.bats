#!/usr/bin/env bats
# The ELN codec gap must stay a NAMED gap, not a quiet pass.
#
# wahoo (Fedora ELN) is the first base in the matrix with no functional
# H.264/H.265 decoder available at all. Measured on the pinned eln-bootc
# digest, 2026-08-25: ELN carries no ffmpeg and no gstreamer1-plugins-ugly,
# RPM Fusion has no ELN branch, ffmpeg-free 8.1.2's only h264 entry is
# `libopenh264`, and the sole openh264 provider in ELN is `noopenh264` —
# Fedora's stub. Encoding a 1s testsrc through it wrote a 0-byte file.
#
# That is exactly the "crippled libavcodec" the codec contract exists to
# catch, so the contract is RIGHT to fire here. What must not happen is the
# fix that hides it: widening the decoder test to accept `libopenh264`, which
# on every other base means a working decoder and on this one means the stub.
# These tests pin the shape of the exemption instead — ELN-only, loud, and
# leaving every other family's hard failure intact.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CONTRACT="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
BASE_PKGS="${REPO_ROOT}/build_scripts/10-base-packages.sh"

@test "the ELN codec gap is announced with a greppable marker" {
  run grep -F 'TUNAOS_CODEC_GAP:' "$CONTRACT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ELN"* ]]
}

@test "the marker goes to stderr, where the diag output already goes" {
  run bash -c "grep -F 'TUNAOS_CODEC_GAP: ELN' '$CONTRACT'"
  [[ "$output" == *">&2"* ]]
}

@test "the decoder test still requires a real ' h264 ' column entry" {
  # The one-line regression that would erase this whole gap: accepting the
  # stub's name. If someone adds it, this fails.
  run grep -E "grep -q ' h264 '" "$CONTRACT"
  [ "$status" -eq 0 ]
  run bash -c "grep -E \"grep -q .*libopenh264\" '$CONTRACT'"
  [ "$status" -ne 0 ]
}

@test "the exemption is ELN-only — other families still exit 1" {
  # The elif chain must keep a bare `exit 1` for everything that is neither
  # ELN nor hummingbird; an unconditional pass here would green a codec-less
  # image on every base.
  run awk '/ffmpeg cannot decode h264/,/^\t\tfi$/' "$CONTRACT"
  [[ "$output" == *'IS_ELN:-false}" == "true"'* ]]
  [[ "$output" == *'IS_HUMMINGBIRD:-false}" != "true"'* ]]
  [[ "$output" == *"exit 1"* ]]
}

# ── The exemption has to be REACHABLE, not just present ────────────────────
#
# Every test above pins the shape of the ELN branch. None of them pinned that
# IS_ELN ever arrives, and it did not: the CI gates bind-mount only this one
# script into the image, so the `source /run/context/build_scripts/lib.sh` at
# the top fails, the flag stays unset, and the branch cannot fire. wahoo's
# gnome, cosmic and kde cells went red on a gap the script is written to
# allow (run 34609709028, tunaOS#2049). A named exemption that never runs is
# the same outcome as no exemption at all, so it is pinned here.

@test "IS_ELN is derived from the image when lib.sh could not be sourced" {
  # The gates mount /vde.sh alone; lib.sh is simply not there to source.
  run grep -qE '^\s*IS_ELN="\$\(_derive_is_eln\)"' "$CONTRACT"
  [ "$status" -eq 0 ]
}

@test "the derivation uses the same os-release signal lib.sh calls primary" {
  # lib.sh: `grep -qE '^ID=eln$' /etc/os-release /usr/lib/os-release`. Two
  # different tests for one fact is how the build and the gate come to
  # disagree about the same image.
  local lib="${REPO_ROOT}/build_scripts/lib.sh"
  run grep -F "grep -qE '^ID=eln\$'" "$lib"
  [ "$status" -eq 0 ]
  run bash -c "awk '/^_derive_is_eln\\(\\)/,/^}/' '$CONTRACT' | grep -F \"grep -qE '^ID=eln\\\$'\""
  [ "$status" -eq 0 ]
  # ID, not VARIANT_ID: 90-image-info.sh's osr_set rewrites VARIANT_ID to the
  # tunaOS variant name, so only ID still reads `eln` in a shipped image.
  run bash -c "awk '/^_derive_is_eln\\(\\)/,/^}/' '$CONTRACT' | grep -F 'VARIANT_ID'"
  [ "$status" -ne 0 ]
}

@test "the derivation answers true only for an exact ID=eln line" {
  eval "$(awk '/^_derive_is_eln\(\)/,/^}/' "$CONTRACT")"
  local d
  d="$(mktemp -d)"
  printf 'ID=eln\nVERSION_ID=11\nVARIANT_ID="wahoo"\n' >"${d}/eln"
  printf 'ID=fedora\nVARIANT_ID="bonito"\n' >"${d}/fedora"
  printf 'ID=eln-lookalike\n' >"${d}/near"

  [ "$(_derive_is_eln "${d}/eln")" = true ]
  [ "$(_derive_is_eln "${d}/fedora")" = false ]
  # Anchored: a substring match would claim any id containing "eln".
  [ "$(_derive_is_eln "${d}/near")" = false ]
  # An unreadable path is not an ELN image, and must not abort under set -e.
  [ "$(_derive_is_eln "${d}/does-not-exist")" = false ]
  # Both canonical paths are consulted, as lib.sh consults both.
  [ "$(_derive_is_eln "${d}/fedora" "${d}/eln")" = true ]
  rm -rf "$d"
}

@test "an explicitly supplied IS_ELN still decides" {
  # Callers that do pass the flag (and any that start) keep control; the
  # derivation fills a gap, it does not override an answer.
  run bash -c "awk '/^if \\[\\[ -z \"\\\$\\{IS_ELN:-\\}\" \\]\\]; then/,/^fi\$/' '$CONTRACT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"_derive_is_eln"* ]]
  # Guarded by -z, so IS_ELN=false from a caller is honoured as false rather
  # than treated as unset and re-derived.
  [[ "$output" == *'-z "${IS_ELN:-}"'* ]]
}

@test "the ELN base install does not pull the noopenh264 stub on purpose" {
  # Installing the stub explicitly would make the gap look deliberate and
  # supported. ffmpeg-free drags it in as a dependency; this file must not
  # name it as if it were a codec.
  run bash -c "awk '/IS_ELN:-false/,/IS_FEDORA == true/' '$BASE_PKGS' | grep -vE '^\\\\s*#' | grep -F noopenh264"
  [ "$status" -ne 0 ]
}
