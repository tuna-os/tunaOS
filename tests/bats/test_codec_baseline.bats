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
  #
  # Scoped to the EL branch rather than the whole file since 2026-08-25: the
  # ELN branch (wahoo) installs ffmpeg-free deliberately and is the one place
  # in this file where it is the correct answer, not a fallback. RPM Fusion
  # publishes no ELN branch and `dnf repoquery` finds neither ffmpeg nor
  # gstreamer1-plugins-ugly in eln-{baseos,appstream,crb,extras}, so there is
  # no encumbered set to fall back FROM. A whole-file grep would have made
  # that honest gap indistinguishable from the EL10 regression this test
  # exists to catch — which is why the assertion moved instead of the code.
  # The EL10 leg is still held to the full set by the test above.
  # The EL branch is the `else` arm of the family chain to the end of file;
  # `^[^#]*` keeps this matching CODE, since that branch's comments recount
  # the v2 history in detail and name ffmpeg-free four times.
  run bash -c "awk '/^else\$/,0' '$BASE_PKGS' | grep -E '^[^#]*ffmpeg-free'"
  [ "$status" -ne 0 ]
  run grep -F 's|/\$basearch/|/x86_64/|' "$BASE_PKGS"
  [ "$status" -eq 0 ]
  # ...and that pin is applied under the v2 detector, not unconditionally.
  run grep -B2 -F 's|/\$basearch/|/x86_64/|' "$BASE_PKGS"
  [[ "$output" == *"is_x86_64_v2"* ]]
}

@test "ELN leg installs the free codec set, and only the free one" {
  # wahoo's codec baseline is NOT equivalent to bonito's or yellowfin's, and
  # that has to stay visible: eln-{baseos,appstream,crb,extras} carry no
  # ffmpeg and no gstreamer1-plugins-ugly (dnf repoquery, 2026-08-25), and
  # RPM Fusion has no ELN branch to install from. If either encumbered name
  # ever appears in this branch it means an ELN source was found — good news
  # that must come with the comment above it updated, not slipped in.
  # Code only, for the same reason as above: this branch's comment block
  # names every package it deliberately does NOT install.
  run bash -c "awk '/IS_ELN:-false/,/IS_FEDORA == true/' '$BASE_PKGS' | grep -vE '^\\s*#'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ffmpeg-free"* ]]
  [[ "$output" == *"gstreamer1-plugin-libav"* ]]
  [[ "$output" != *"gstreamer1-plugins-ugly"* ]]
  [[ "$output" != *"rpmfusion"* ]]
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
  # variable, then grepped. stderr goes to a file, not /dev/null — discarding
  # it is how guppy:xfce (run 31201546516) failed this check with no evidence
  # of what ffmpeg actually said.
  run grep -F '_ffmpeg_decoders="$(ffmpeg -hide_banner -decoders 2>"$_ffmpeg_stderr_file")"' "$CONTRACT"
  [ "$status" -eq 0 ]
  run grep -F "grep -q ' h264 ' <<<\"\$_ffmpeg_decoders\"" "$CONTRACT"
  [ "$status" -eq 0 ]
  # And a missing decoder must be fatal (exit 1 in that branch), not a warning.
  #
  # Read over the whole branch rather than the three lines after the message:
  # the branch carries a named ELN exemption since 2026-08-25 (ELN ships no
  # functional H.264 decoder at all — see tests/bats/test_eln_codec_gap.bats
  # for the measurement), and its comment block sits between the message and
  # the exit. `-A3` was measuring comment proximity, not fatality.
  run awk '/ffmpeg cannot decode h264/,/^\t\tfi$/' "$CONTRACT"
  [[ "$output" == *"exit 1"* ]]
  # Fatality is the DEFAULT: every exemption in that branch must name the
  # base it exempts, so a blanket `if false` can never creep in.
  run bash -c "awk '/ffmpeg cannot decode h264/,/^\t\tfi\$/' '$CONTRACT' | grep -E '^\\s*(if|elif)'"
  [ "$status" -eq 0 ]
  while read -r line; do
    [[ "$line" == *"IS_ELN"* || "$line" == *"IS_HUMMINGBIRD"* ]] || {
      echo "unnamed exemption in the h264 branch: ${line}" >&2
      return 1
    }
  done <<<"$output"
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
  #
  # The exact code depends on the SIGPIPE disposition the harness inherited,
  # so this asserts "nonzero", not "141". With SIGPIPE at its default the
  # writer dies of the signal and bash reports 141 (128+13) — that is the
  # container-build case the contract actually runs in. When some ancestor
  # already set SIGPIPE to SIG_IGN, children inherit the ignore, writes fail
  # with EPIPE instead, and the pipeline reports 1 — that is the GitHub
  # Actions case, whose Node-based runner ignores SIGPIPE. Same bug either
  # way: the pipeline fails WITH the decoder present. Pinning 141 made this
  # test itself a false failure on CI.
  run bash -c "set -o pipefail; '${BATS_TEST_TMPDIR}/fake-decoders' 2>/dev/null | grep -q ' h264 '"
  [ "$status" -ne 0 ]
  # New (captured) form: passes.
  run bash -c "set -o pipefail; d=\"\$('${BATS_TEST_TMPDIR}/fake-decoders')\"; grep -q ' h264 ' <<<\"\$d\""
  [ "$status" -eq 0 ]
}

# ── Failure-evidence dump ────────────────────────────────────────────────────
# When the h264 probe fires, the contract must name its evidence: which ffmpeg
# ran, its configure line's decoder kill-switches, what it wrote to stderr,
# and what the decoder list held. guppy:xfce (run 31201546516) failed this
# check against a source-built ffmpeg whose USE line said the decoder should
# exist, and three container reproductions could not replicate it — the next
# failing run has to answer for itself.

# Extract the codec-baseline block and run it against a fake ffmpeg on PATH.
run_codec_block() {
  local bin="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$bin"
  cp "${BATS_TEST_TMPDIR}/fake-ffmpeg" "${bin}/ffmpeg"
  chmod +x "${bin}/ffmpeg"
  local block
  block="$(awk '/── Codec baseline ──/,/── KDE version-skew guard/' "$CONTRACT" | sed '$d')"
  PATH="${bin}:/usr/bin:/bin" bash -c "
    set -euo pipefail
    require_any_glob() { :; }
    require_command() { :; }
    IS_HUMMINGBIRD=false
    ${block}
  "
}

@test "a decoder-less ffmpeg fails AND dumps codec_diag evidence" {
  cat > "${BATS_TEST_TMPDIR}/fake-ffmpeg" <<'FAKE'
#!/usr/bin/env bash
case "$*" in
*-decoders*) echo " V....D vp9    Google VP9"; echo "warning: h264 decoder disabled at configure time" >&2 ;;
*-version*)  echo "ffmpeg version 9.9-test"; echo "built with test"; echo "configuration: --disable-decoder=h264" ;;
esac
FAKE
  run run_codec_block
  [ "$status" -eq 1 ]
  [[ "$output" == *"cannot decode h264"* ]]
  [[ "$output" == *"codec_diag: ffmpeg="* ]]
  [[ "$output" == *"codec_diag: configure --disable-decoder=h264"* ]]
  [[ "$output" == *"codec_diag: decoders_stderr: warning: h264 decoder disabled at configure time"* ]]
  [[ "$output" == *"ffmpeg version 9.9-test"* ]]
}

@test "an ffmpeg that will not run fails on its own branch with evidence" {
  cat > "${BATS_TEST_TMPDIR}/fake-ffmpeg" <<'FAKE'
#!/usr/bin/env bash
case "$*" in
*-decoders*) echo "error while loading shared libraries: libavcodec.so.62" >&2; exit 127 ;;
*-version*)  echo "ffmpeg version 9.9-test"; echo "built with test" ;;
esac
FAKE
  run run_codec_block
  [ "$status" -eq 1 ]
  [[ "$output" == *"would not run"* ]]
  [[ "$output" == *"codec_diag: decoders_stderr: error while loading shared libraries"* ]]
}

@test "a healthy ffmpeg passes silently — no codec_diag noise on green" {
  cat > "${BATS_TEST_TMPDIR}/fake-ffmpeg" <<'FAKE'
#!/usr/bin/env bash
case "$*" in
*-decoders*) echo " V....D h264                 H.264 / AVC" ;;
*-version*)  echo "ffmpeg version 9.9-test" ;;
esac
FAKE
  run run_codec_block
  [ "$status" -eq 0 ]
  [[ "$output" != *"codec_diag"* ]]
}
