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

@test "the ELN base install does not pull the noopenh264 stub on purpose" {
  # Installing the stub explicitly would make the gap look deliberate and
  # supported. ffmpeg-free drags it in as a dependency; this file must not
  # name it as if it were a codec.
  run bash -c "awk '/IS_ELN:-false/,/IS_FEDORA == true/' '$BASE_PKGS' | grep -vE '^\\\\s*#' | grep -F noopenh264"
  [ "$status" -ne 0 ]
}
