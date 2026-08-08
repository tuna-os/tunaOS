#!/usr/bin/env bash
# record-timelapse.sh — capture the QEMU framebuffer during an install and
# assemble a WebM timelapse, so a matrix cell leaves behind something a human
# can watch instead of an 80,000-line serial log.
#
# Ported from tuna-os/wootc tests/e2e/record-video.sh, with three deliberate
# differences:
#
#   * wootc drives QEMU inside a container and reaches the monitor with
#     `podman exec`. Here QEMU runs directly on the runner, so the monitor
#     unix socket is addressed straight through socat — the same channel
#     iso-e2e.sh's screenshot() already uses for its screendump fallback.
#   * No title cards. wootc has one linear story (Windows → deploy → Linux);
#     a LUKS cell is one install, and the phase boundaries are already in the
#     serial log next to the frame timestamps.
#   * Assembly NEVER fails the caller. A cell that installs correctly but
#     cannot be filmed is a green cell; treating a missing encoder as a test
#     failure would turn a reporting nicety into a gate.
#
# Capture is `screendump` over the QEMU monitor, which is cheap enough to run
# on a loop. That choice has one documented limit, and it is the reason this
# does not simply call iso-e2e.sh's screenshot(): under virgl/GL scanout the
# monitor answers "no surface" and screendump yields nothing (see the long
# comment at iso-e2e.sh:831). screenshot() handles that by bridging VNC per
# capture — a fresh socat listener and up to 5s of readiness polling EACH
# TIME, which is right for a handful of stills and wrong for the ~300 frames
# a ten-minute install produces. The LUKS matrix runs on GPU-less hosted
# runners, where QEMU_GPU_ARGS is the plain `-vga virtio -display none` path
# and screendump works. On a virgl host this records nothing and says so,
# rather than pretending.
#
# Usage:
#   record-timelapse.sh start <monitor-sock> <outdir> [interval-seconds]
#   record-timelapse.sh stop  <outdir>
set -Eeuo pipefail

command="${1:?usage: record-timelapse.sh start|stop ...}"

FPS="${TUNAOS_TIMELAPSE_FPS:-10}"

snap_loop() {
	local sock="$1" outdir="$2" interval="$3"
	local n=0 frame
	mkdir -p "$outdir/frames"
	while :; do
		frame="$(printf '%s/frames/f%06d.ppm' "$outdir" "$n")"
		# screendump writes from QEMU's perspective, so the path must be one
		# QEMU can write — it is the same filesystem here.
		echo "screendump ${frame}" | socat - "UNIX-CONNECT:${sock}" >/dev/null 2>&1 || true
		# Only advance the counter when a frame actually landed. ffmpeg's
		# image2 demuxer needs a gapless sequence; a hole makes it stop at the
		# gap and silently produce a truncated video.
		[[ -s "$frame" ]] && n=$((n + 1)) || rm -f "$frame"
		sleep "$interval"
	done
}

assemble() {
	local outdir="$1"
	local fdir="$outdir/frames"
	local nframes
	# The directory may not exist: `stop` can be reached before the first
	# capture landed (QEMU died early, or the monitor socket never appeared).
	# Without this, `find` on a missing path fails, and under `set -o pipefail`
	# that non-zero propagates through the command substitution and — with
	# `set -e` — exits this script non-zero, failing an install that was
	# otherwise fine. That is the exact contract this file exists to keep, and
	# it was broken until a test caught it.
	mkdir -p "$fdir"
	nframes="$(find "$fdir" -maxdepth 1 -type f -name 'f*.ppm' 2>/dev/null | wc -l)"
	printf '%s\n' "$nframes" >"$outdir/frame-count.txt"

	if [[ "$nframes" -eq 0 ]]; then
		# The virgl case, or a QEMU that died before the first capture. Say
		# which, because "no video" with no reason reads as a broken script.
		echo "==> No frames captured; no timelapse. On a virgl/GL-scanout host" >&2
		echo "    screendump has no surface — that is expected there." >&2
		return 0
	fi

	if ! command -v ffmpeg >/dev/null 2>&1; then
		echo "==> ${nframes} frames captured but ffmpeg is absent; leaving frames only" >&2
		return 0
	fi

	# -f image2 with an explicit pattern: without it ffmpeg guesses from the
	# first filename and has been known to pick the wrong demuxer for .ppm.
	ffmpeg -y -loglevel warning -framerate "$FPS" \
		-f image2 -i "$fdir/f%06d.ppm" \
		-c:v libvpx-vp9 -b:v 1M -pix_fmt yuv420p \
		"$outdir/timelapse.webm" </dev/null || {
		echo "==> ffmpeg could not assemble the timelapse; frames kept" >&2
		return 0
	}

	# A still poster so a gallery can show something before anyone presses
	# play, and so GitHub can render it inline. Half the capture rate and a
	# fixed width keeps it small enough to commit if we ever want to.
	ffmpeg -y -loglevel warning -framerate "$FPS" \
		-f image2 -i "$fdir/f%06d.ppm" \
		-vf 'fps=5,scale=640:-2:flags=lanczos' -loop 0 \
		-c:v libwebp -quality 60 -compression_level 6 \
		"$outdir/timelapse-poster.webp" </dev/null || true

	echo "==> Timelapse: $outdir/timelapse.webm (${nframes} frames @ ${FPS}fps)"
}

case "$command" in
start)
	sock="${2:?start needs the QEMU monitor socket}"
	outdir="${3:?start needs an output directory}"
	interval="${4:-${TUNAOS_TIMELAPSE_INTERVAL:-2}}"
	mkdir -p "$outdir"
	# Recording is best-effort: if the monitor socket never appears the loop
	# simply captures nothing, and assemble() reports that. It must not wedge
	# the install waiting for it.
	# Redirect the loop's descriptors rather than letting it inherit them: a
	# backgrounded child holding the caller's stdout keeps readers of that
	# pipe blocked until it exits, and this one runs until `stop`. That hung
	# the test suite for two minutes before it was redirected here.
	snap_loop "$sock" "$outdir" "$interval" >"$outdir/recorder.log" 2>&1 </dev/null &
	printf '%s\n' "$!" >"$outdir/.recorder.pid"
	echo "==> Timelapse recording started (every ${interval}s → ${outdir}/frames)"
	;;
stop)
	outdir="${2:?stop needs the output directory}"
	if [[ -f "$outdir/.recorder.pid" ]]; then
		kill "$(cat "$outdir/.recorder.pid")" 2>/dev/null || true
		wait "$(cat "$outdir/.recorder.pid")" 2>/dev/null || true
		rm -f "$outdir/.recorder.pid"
	fi
	assemble "$outdir"
	;;
*)
	echo "usage: record-timelapse.sh start|stop ..." >&2
	exit 2
	;;
esac
