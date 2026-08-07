#!/usr/bin/env bats
# Codec baseline: what the build installs and what the contract asserts must
# name the same pieces, per packaging family.
#
# The gap these pin: the EL10 x86_64_v2 leg shipped ffmpeg-free only (no
# H.264/H.265 decode at all) and marlin shipped gst-plugins-ugly without
# gst-libav (x264 ENcoder, no mainstream DEcoder) — both green, because
# nothing anywhere verified a codec. See the "Codec baseline" section of
# build_scripts/checks/verify-desktop-experience.sh.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
BASE_PKGS="${REPO_ROOT}/build_scripts/10-base-packages.sh"
CONTRACT="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"

@test "EL10 leg installs the gstreamer decode pair from epel-multimedia" {
  # Extract the dnf transaction that carries the epel-multimedia enablerepo
  # and check the two decode-critical names ride in it.
  run awk '/--enablerepo=epel-multimedia/,/^$/' "$BASE_PKGS"
  [[ "$output" == *"gstreamer1-plugin-libav"* ]]
  [[ "$output" == *"gstreamer1-plugins-ugly"* ]]
}

@test "EL10 x86_64_v2 no longer falls back to ffmpeg-free" {
  # The crippled v2-only branch is gone; the v2 accommodation is a basearch
  # pin on the same repo, not a different (free-codec) package set. Match
  # code only — the history lives on in comments.
  run grep -E '^[^#]*ffmpeg-free' "$BASE_PKGS"
  [ "$status" -ne 0 ]
  run grep -F 's|/\$basearch/|/x86_64/|' "$BASE_PKGS"
  [ "$status" -eq 0 ]
  # ...and that pin is applied under the v2 detector, not unconditionally.
  run grep -B2 -F 's|/\$basearch/|/x86_64/|' "$BASE_PKGS"
  [[ "$output" == *"is_x86_64_v2"* ]]
}

@test "Fedora leg installs gstreamer1-plugin-libav alongside RPM Fusion ffmpeg" {
  # Both must appear inside the same Fedora branch (between the IS_FEDORA
  # test and the following elif).
  run awk '/IS_FEDORA == true/,/^else$/' "$BASE_PKGS"
  [[ "$output" == *"gstreamer1-plugin-libav"* ]]
  [[ "$output" == *"gstreamer1-plugins-ugly"* ]]
}

@test "Arch base installs gst-libav" {
  run grep -E '^\s*gst-libav' "${REPO_ROOT}/Containerfile.arch"
  [ "$status" -eq 0 ]
}

@test "contract asserts the libav plugin at each family's measured path" {
  for g in \
    '/usr/lib64/gstreamer-1.0/libgstlibav.so' \
    '/usr/lib/gstreamer-1.0/libgstlibav.so' \
    '/usr/lib/*/gstreamer-1.0/libgstlibav.so'; do
    grep -qF "'$g'" "$CONTRACT" || { echo "missing contract glob: $g" >&2; return 1; }
  done
}

@test "contract proves h264 decode through ffmpeg, not just plugin presence" {
  # The plugin file existing is satisfiable by a free-codec libavcodec — the
  # exact v2 failure — so the contract must interrogate ffmpeg itself.
  run grep -E 'ffmpeg -hide_banner -decoders.*grep -q .{0,3}h264' "$CONTRACT"
  [ "$status" -eq 0 ]
  # And a missing decoder must be fatal (exit 1 in that branch), not a warning.
  run grep -A3 'ffmpeg cannot decode h264' "$CONTRACT"
  [[ "$output" == *"exit 1"* ]]
}
