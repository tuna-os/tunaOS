#!/usr/bin/env bats
# A failing cell must say why in the artifact, not only in a job log.
#
# The sweep recorded a bare "exit 1" for 6 of the 14 failing cells in run
# 34692178123 — wahoo:{gnome,cosmic,kde}, skipjack:gnome, yellowfin:gnome and
# bonito-rawhide:kde. Every one of them had printed a perfectly clear reason
# that the sweep then threw away, because it matched only the "^missing
# (required|unit)" prefix and about twenty other failure lines in
# verify-desktop-experience.sh do not start that way. The verdicts reached
# docs/MATRIX-STATUS.md as "exit 1", diagnosable only by opening the job log,
# which is the habit this sweep exists to remove.
#
# The fixtures below are taken verbatim from those job logs.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SWEEP="${REPO_ROOT}/.github/workflows/desktop-contract-sweep.yml"

# The extraction under test, kept identical to the workflow's. The guard test
# below fails if the two ever drift.
extract() {
	local out="$1" exitcode="$2" reason
	reason=$(grep -m1 -E "^missing (required|unit)" <<<"$out" ||
		grep -vE "^(codec_diag:|::(warning|notice|error))" <<<"$out" |
		grep -vE "^[[:space:]]*$" | tail -1 ||
		echo "exit ${exitcode}")
	reason=${reason:-exit ${exitcode}}
	printf '%s\n' "$reason"
}

@test "the workflow still uses the pipeline these tests exercise" {
	# tunaOS#1730: a fixture test that has drifted from the code it claims to
	# cover passes while proving nothing.
	grep -qF 'grep -m1 -E "^missing (required|unit)"' "$SWEEP"
	grep -qF 'grep -vE "^(codec_diag:|::(warning|notice|error))"' "$SWEEP"
}

@test "a codec failure names the codec, not the exit status" {
	# wahoo:gnome, job 103549280539.
	run extract "$(printf '%s\n' \
		"GNOME 51 meets the floor of 50" \
		"::warning::systemd-analyze verify reported unit problems (desktop=gnome)" \
		"ffmpeg cannot decode h264 — a free/crippled libavcodec is installed" \
		"codec_diag: ffmpeg=/usr/sbin/ffmpeg" \
		"codec_diag: configure --disable-decoder='h264,hevc,vc1,vvc'")" 1
	[[ "$output" == "ffmpeg cannot decode h264"* ]]
}

@test "a version-floor failure names the floor" {
	# yellowfin:gnome and skipjack:gnome, jobs 103549280433 / 103549280489.
	run extract "GNOME 49 is below the floor: nothing below GNOME 50 ships (maintainer directive 2026-09-03; the target is 51). This image's gnome-shell reports major version 49." 1
	[[ "$output" == "GNOME 49 is below the floor"* ]]
}

@test "the last verdict wins when a cell fails more than one way" {
	# bonito-rawhide:kde, job 103549281707.
	run extract "$(printf '%s\n' \
		"invalid desktop file: /usr/share/applications/org.kde.kded6.desktop" \
		"missing flatpak preinstall declaration: org.mozilla.firefox")" 1
	[ "$output" = "missing flatpak preinstall declaration: org.mozilla.firefox" ]
}

@test "a 'missing required' cell reads exactly as it did before" {
	# The prefix match stays first preference, so no cell's recorded reason
	# changes shape. bonito-rawhide:gnome, run 34692178123.
	local line="missing required path: none of [/usr/lib64/gstreamer-1.0/libgstlibav.so] exist"
	run extract "$(printf '%s\n%s\n' "GNOME 51 meets the floor of 50" "$line")" 1
	[ "$output" = "$line" ]
}

@test "output that is all noise still falls back to the exit status" {
	run extract "$(printf '%s\n' "codec_diag: only noise" "::warning::also noise")" 7
	[ "$output" = "exit 7" ]
}

@test "empty output falls back to the exit status" {
	run extract "" 3
	[ "$output" = "exit 3" ]
}
