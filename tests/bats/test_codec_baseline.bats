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
  # exact v2 failure — so the contract must interrogate ffmpeg itself. The
  # probe must use the capture-first form: the output is captured into a
  # variable, then grepped.
  run grep -F '_ffmpeg_decoders="$(ffmpeg -hide_banner -decoders 2>/dev/null)"' "$CONTRACT"
  [ "$status" -eq 0 ]
  run grep -F "grep -q ' h264 ' <<<\"\$_ffmpeg_decoders\"" "$CONTRACT"
  [ "$status" -eq 0 ]
  # And a missing decoder must be fatal (exit 1 in that branch), not a warning.
  run grep -A3 'ffmpeg cannot decode h264' "$CONTRACT"
  [[ "$output" == *"exit 1"* ]]
  # ffmpeg-would-not-run is a DIFFERENT diagnosis with a different fix
  # (packaging deps, not codec sourcing) — it must have its own fatal branch,
  # never fold into "crippled libavcodec".
  run grep -A3 'ffmpeg is installed but would not run' "$CONTRACT"
  [[ "$output" == *"exit 1"* ]]
}

@test "the h264 probe never pipes ffmpeg straight into grep -q" {
  # The piped form is a false-negative machine, not a style nit: grep -q
  # exits at the first match, ffmpeg is still writing its ~30 KB decoder
  # list, takes SIGPIPE (exit 141), and under the contract's pipefail the
  # pipeline reports failure WITH the decoder present. Measured on
  # ubuntu:noble (ffmpeg 6.1.1): 141 on five of five runs; it failed
  # gurnard:pantheon's proof build (run 31196812732) blaming a "crippled
  # libavcodec" the image did not have.
  run grep -E 'ffmpeg -hide_banner -decoders[^|]*\|[[:space:]]*grep' "$CONTRACT"
  [ "$status" -ne 0 ]
}

@test "the SIGPIPE mechanism is real, and the captured form is immune" {
  # Behavioral proof with a generator standing in for ffmpeg: the match line
  # first, then (after grep -q has certainly exited) more output than a pipe
  # buffer holds, so the writer hits the closed pipe deterministically.
  cat > "${BATS_TEST_TMPDIR}/fake-decoders" <<'GEN'
#!/usr/bin/env bash
echo " VFS..D h264                 H.264 / AVC"
sleep 0.3
for _ in $(seq 1 3000); do
  echo " V....D someothercodec       filler line to overrun the pipe buffer"
done
GEN
  chmod +x "${BATS_TEST_TMPDIR}/fake-decoders"
  # Old (piped) form under pipefail: fails despite the decoder being there.
  run bash -c "set -o pipefail; '${BATS_TEST_TMPDIR}/fake-decoders' | grep -q ' h264 '"
  [ "$status" -eq 141 ]
  # New (captured) form: passes.
  run bash -c "set -o pipefail; d=\"\$('${BATS_TEST_TMPDIR}/fake-decoders')\"; grep -q ' h264 ' <<<\"\$d\""
  [ "$status" -eq 0 ]
}
