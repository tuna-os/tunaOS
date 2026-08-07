#!/usr/bin/env bats
# record-timelapse.sh turns a matrix cell into something watchable.
#
# The property these tests defend is not "it makes a video" — it is that it
# NEVER fails the caller. It runs inside the LUKS e2e flow, where a cell that
# installs correctly but cannot be filmed is still a green cell. If a missing
# encoder, an absent monitor socket or a virgl host could make this exit
# non-zero, a reporting nicety would start failing installs that work.
#
# ffmpeg and socat are deliberately NOT assumed present: this repo's own CI
# container lacks both, and so will anyone running the suite locally. Each
# test therefore controls what is on PATH rather than inheriting it.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/record-timelapse.sh"

setup() {
	OUT="$BATS_TEST_TMPDIR/out"
	mkdir -p "$OUT"
	BIN="$BATS_TEST_TMPDIR/bin"
	mkdir -p "$BIN"
	# A PATH with the shell utilities the script needs and nothing else, so a
	# host that happens to have ffmpeg cannot make the "encoder absent" test
	# vacuous. (The sibling reachability test file had exactly that bug: it
	# left /usr/bin on PATH, so its negative cases asserted nothing on hosts
	# that ship the tool.)
	local u bin
	for u in bash sh find wc rm cat printf sleep kill mkdir sed; do
		bin="$(command -v "$u" 2>/dev/null)" || continue
		ln -sf "$bin" "$BIN/$u"
	done
}

make_frames() {
	mkdir -p "$OUT/frames"
	local i
	for i in 0 1 2; do
		printf 'P6\n1 1\n255\n\0\0\0' >"$(printf '%s/frames/f%06d.ppm' "$OUT" "$i")"
	done
}

@test "record-timelapse.sh exists and is executable" {
	run test -x "$SCRIPT"
	[ "$status" -eq 0 ]
}

@test "usage error is the only non-zero exit" {
	run bash "$SCRIPT"
	[ "$status" -ne 0 ]
}

# The virgl / no-surface case. screendump legitimately produces nothing there,
# and the run must stay green.
@test "stop with no frames succeeds and explains why there is no video" {
	run env PATH="$BIN" bash "$SCRIPT" stop "$OUT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"No frames captured"* ]]
	[[ "$output" == *"virgl"* ]]
	[ "$(cat "$OUT/frame-count.txt")" = "0" ]
}

# Frames captured but no encoder on the box: keep the frames, say so, stay
# green. This is the state of this very container.
@test "stop without ffmpeg keeps the frames and still succeeds" {
	make_frames
	run env PATH="$BIN" bash "$SCRIPT" stop "$OUT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"ffmpeg is absent"* ]]
	[ "$(cat "$OUT/frame-count.txt")" = "3" ]
	[ -f "$OUT/frames/f000000.ppm" ]
}

@test "stop assembles a webm when ffmpeg is available" {
	make_frames
	cat >"$BIN/ffmpeg" <<-'EOF'
		#!/bin/sh
		# Emulate ffmpeg's contract narrowly: the output path is the last arg.
		for last; do :; done
		printf 'stub' > "$last"
		exit 0
	EOF
	chmod +x "$BIN/ffmpeg"

	run env PATH="$BIN" bash "$SCRIPT" stop "$OUT"
	[ "$status" -eq 0 ]
	[ -f "$OUT/timelapse.webm" ]
	[[ "$output" == *"3 frames"* ]]
}

# A failing encoder must not fail the install either — the frames are still
# worth keeping and the cell's verdict is unaffected.
@test "an ffmpeg that fails leaves the frames and still succeeds" {
	make_frames
	cat >"$BIN/ffmpeg" <<-'EOF'
		#!/bin/sh
		exit 1
	EOF
	chmod +x "$BIN/ffmpeg"

	run env PATH="$BIN" bash "$SCRIPT" stop "$OUT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"could not assemble"* ]]
	[ -f "$OUT/frames/f000000.ppm" ]
}

# start must return immediately even when the monitor socket will never
# appear: it is called before the guest is up, and must not wedge the install.
@test "start returns promptly with no monitor socket and records a pid" {
	run env PATH="$BIN:$PATH" bash "$SCRIPT" start "$OUT/nonexistent.sock" "$OUT" 1
	[ "$status" -eq 0 ]
	[ -f "$OUT/.recorder.pid" ]
	# Clean up the backgrounded loop this test just started.
	kill "$(cat "$OUT/.recorder.pid")" 2>/dev/null || true
}

# ffmpeg's image2 demuxer stops at the first gap in the sequence, so a frame
# that failed to capture must not consume an index — otherwise the video is
# silently truncated at the hole rather than being short by one frame.
@test "the frame counter only advances on a frame that actually landed" {
	run grep -n 'n=\$((n + 1)) || rm -f' "$SCRIPT"
	[ "$status" -eq 0 ]
}
