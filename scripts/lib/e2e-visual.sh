#!/usr/bin/env bash
# e2e-visual.sh — framebuffer capture and visual verification for iso-e2e.
#
# This module is sourced by scripts/iso-e2e.sh. Its interface is the four
# functions below; callers provide the run context explicitly through these
# variables before invoking them:
#
#   OUTPUT_DIR   artifact directory (required)
#   MONITOR_SOCK QEMU monitor unix socket (required for screendump fallback)
#   SCRIPT_DIR   repository scripts directory (required by screenshot_compare)
#   VARIANT      image variant (optional; reference lookup defaults to unknown)
#   FLAVOR       desktop flavor (optional; reference lookup defaults to unknown)
#
# Optional TBOX_E2E_VNC_PORT and TBOX_E2E_PAINT_TIMEOUT tune the VNC bridge
# and paint deadline. SCREENSHOT_STDDEV and VNC_BRIDGE_PORT are outputs kept in
# the caller's shell so the orchestrator can record evidence across calls.
# Keeping this file free of argument parsing and VM lifecycle setup lets its
# behavior be exercised without booting QEMU.

# Take a screenshot. Best-effort, and deliberately two-path.
#
# `screendump` cannot capture a guest that is scanning out through virgl. Once
# a Wayland compositor takes over, the framebuffer lives in a GL texture that
# QEMU's console layer never sees, and the monitor answers:
#
#   (qemu) screendump /path/shot.ppm
#   Error: no surface
#
# Attaching -vnc is necessary but NOT sufficient: with VNC listening,
# screendump still reports "no surface" under GL scanout. Verified on hardware
# 2026-07-26 — it succeeds at the pre-GL text console and fails the moment
# cosmic-comp starts, which is precisely the window we care about.
#
# The VNC *client* path does work, because the VNC server reads the texture
# back for its clients. Capturing through it produced the first image ever
# taken of the cosmic live session with the installer on screen.
#
# So: prefer VNC capture whenever the socket exists, and keep screendump as
# the fallback for the plain -vga virtio path, where it is perfectly good.
screenshot() {
	local label="$1"
	local out="${OUTPUT_DIR}/${label}.ppm"
	local png="${OUTPUT_DIR}/${label}.png"
	local vnc_sock="${OUTPUT_DIR}/vnc.sock"

	local cap_log="${OUTPUT_DIR}/vnc-capture-${label}.log"

	if [[ -S "$vnc_sock" ]] && command -v vncdo &>/dev/null && command -v socat &>/dev/null; then
		# vncdo speaks TCP, so bridge the unix socket for the moment of capture.
		#
		# A FRESH PORT PER CAPTURE, and no `fork` — this is bug 2 of #946.
		# The old bridge was `TCP-LISTEN:...,fork`, which forks a child per
		# connection; `kill $bridge` reaps only the listener, so children
		# bridging to a socket whose QEMU has since been killed survive and
		# keep the port warm. The next capture then connects to one of those
		# corpses and vncdo reads ECONNRESET — which is exactly the reported
		# signature: the live capture (first use of the port) succeeds, the
		# installed capture (always second) fails with "Connection reset by
		# peer". One capture is one connection, so `fork` bought nothing.
		VNC_BRIDGE_PORT=$((${VNC_BRIDGE_PORT:-${TBOX_E2E_VNC_PORT:-5999}} + 1))
		local port="$VNC_BRIDGE_PORT"
		# bind=127.0.0.1: vncdo connects to loopback, so there is no reason to
		# expose the guest console on every host interface, however briefly —
		# these runs happen on bare-metal hosts on a real LAN.
		socat "TCP-LISTEN:${port},bind=127.0.0.1,reuseaddr" "UNIX-CONNECT:${vnc_sock}" >>"$cap_log" 2>&1 &
		local bridge=$!
		# Wait for the listener instead of sleeping at it: on a loaded host
		# 1s was sometimes short, and the failure was indistinguishable from
		# a real capture failure.
		#
		# Liveness of *this* socat is checked first: a listening port alone
		# proves nothing, since a leftover bridge or an unrelated service can
		# hold it while our socat failed to bind and exited. And the port match
		# is anchored on whitespace/end-of-line — `\b` is not a word boundary
		# in grep's default BRE, so ":5999\b" never matched `ss` output as
		# intended (and a bare ":5999" would also match ":59990").
		local ready=0
		for _ in $(seq 1 20); do
			if ! kill -0 "$bridge" 2>/dev/null; then
				echo "==> VNC bridge exited before listening on ${port}" >>"$cap_log"
				break
			fi
			if command -v ss &>/dev/null; then
				ss -ltn 2>/dev/null | grep -Eq "127\.0\.0\.1:${port}([[:space:]]|$)" && {
					ready=1
					break
				}
			else
				sleep 1
				ready=1
				break
			fi
			sleep 0.25
		done
		[[ "$ready" == 1 ]] || echo "==> VNC bridge never listened on ${port}" >>"$cap_log"
		# Errors go to a per-label log, not /dev/null. #946 bug 2 sat
		# undiagnosed because this line discarded both vncdo's and socat's
		# output, so a failed capture said only "rendered=absent".
		vncdo -s "127.0.0.1::${port}" capture "$png" >>"$cap_log" 2>&1 || true
		kill "$bridge" 2>/dev/null || true
		wait "$bridge" 2>/dev/null || true
		if [[ -s "$png" ]]; then
			echo "==> Screenshot saved: ${png} (vnc)"
			return 0
		fi
		echo "==> VNC capture failed; falling back to screendump (see ${cap_log})" >&2
	fi

	if [[ -S "$MONITOR_SOCK" ]] && command -v socat &>/dev/null; then
		echo "screendump ${out}" | socat - "UNIX-CONNECT:${MONITOR_SOCK}" >/dev/null 2>&1 || true
		if [[ -f "$out" ]]; then
			echo "==> Screenshot saved: ${out}"
		else
			# Say so rather than leaving a silently absent artifact: on the
			# virgl path this is expected, and vncdo is the missing piece.
			echo "==> No screenshot captured (screendump found no surface; install vncdotool for the virgl path)" >&2
		fi
	fi
}

# Compare screenshot against a reference using ImageMagick SSIM (Layer 2).
# Returns 0 if similarity >= threshold (0.99 = 99%), 1 otherwise.
# Reference images are stored in tests/reference/{variant}-{flavor}-reference.png
# Generate with: convert reference.ppm reference.png && cp to tests/reference/
screenshot_compare() {
	local label="$1"
	local ref_dir="${SCRIPT_DIR}/tests/reference"
	local variant_flavor="${VARIANT:-unknown}-${FLAVOR:-unknown}"
	local ref="${ref_dir}/${variant_flavor}-reference.png"
	local cap="${OUTPUT_DIR}/${label}.ppm"

	if [[ ! -f "$ref" ]]; then
		echo "==> No reference image at ${ref} — skipping comparison"
		return 0
	fi
	if [[ ! -f "$cap" ]]; then
		echo "==> No captured screenshot at ${cap} — cannot compare"
		return 1
	fi
	if ! command -v compare &>/dev/null; then
		echo "==> ImageMagick compare not available — skipping comparison"
		return 0
	fi

	# Convert PPM to PNG for comparison
	local cap_png="${OUTPUT_DIR}/${label}.png"
	if command -v convert &>/dev/null; then
		convert "$cap" "$cap_png" 2>/dev/null || true
	fi

	# SSIM comparison: 1.0 = identical, >0.99 = perceptually same
	local ssim
	ssim=$(compare -metric SSIM "$ref" "${cap_png:-$cap}" "${OUTPUT_DIR}/${label}-diff.png" 2>&1 || true)
	local threshold=0.99

	if [[ -n "$ssim" ]]; then
		local ok
		ok=$(echo "$ssim >= $threshold" | bc 2>/dev/null || echo 0)
		if [[ "$ok" == "1" ]]; then
			echo "==> ✅ Screenshot matches reference (SSIM: $ssim >= $threshold)"
			return 0
		else
			echo "==> ⚠️  Screenshot differs from reference (SSIM: $ssim < $threshold)"
			echo "    Diff image: ${OUTPUT_DIR}/${label}-diff.png"
			# Non-blocking — emit ::warning, don't fail
			echo "::warning::Screenshot comparison: SSIM $ssim below threshold $threshold"
			return 0
		fi
	else
		echo "==> SSIM comparison produced no output — skipping"
		return 0
	fi
}

# Sanity-check a captured screenshot: it must exist and show actual content
# (not a black/blank framebuffer). Used as the readiness fallback when the
# serial marker never arrives — the bootc base kernels ship
# CONFIG_SERIAL_8250=m, so the readiness marker often cannot reach the serial
# console even though the live session is up (see research.md).
# Returns 0 if the screenshot looks like a rendered screen, 1 otherwise.
screenshot_sane() {
	local label="$1"
	# screenshot() writes .png on the VNC path and .ppm on the screendump
	# path, and this only ever looked for .ppm — so on the virgl path, where
	# VNC is the ONLY thing that captures anything at all, a perfectly good
	# screenshot read as "no screenshot ... cannot verify". Take whichever
	# landed; ImageMagick measures both the same way.
	local cap="${OUTPUT_DIR}/${label}.png"
	[[ -s "$cap" ]] || cap="${OUTPUT_DIR}/${label}.ppm"
	if [[ ! -s "$cap" ]]; then
		echo "==> No screenshot at ${OUTPUT_DIR}/${label}.{png,ppm} — cannot verify via fallback" >&2
		return 1
	fi
	if ! command -v convert &>/dev/null; then
		# Without ImageMagick we can only check the file is non-trivial. The
		# 100kB floor assumes an uncompressed PPM; PNG of a near-blank screen
		# compresses far below it, so this heuristic cannot judge a PNG at all
		# and must not answer for one.
		if [[ "$cap" == *.png ]]; then
			echo "==> ImageMagick absent; cannot judge PNG ${cap} for blankness" >&2
			return 1
		fi
		local size
		size=$(stat -c%s "$cap" 2>/dev/null || echo 0)
		[[ "$size" -gt 100000 ]] && return 0
		return 1
	fi
	# standard_deviation ~0 means a uniform (blank/black) screen. A rendered
	# DM/desktop always has structure. fx output is 0..1.
	local stddev
	stddev=$(convert "$cap" -colorspace Gray -format "%[fx:standard_deviation]" info: 2>/dev/null || echo 0)
	# Published so callers can record the measurement itself, not just the
	# verdict: "blank" and "stddev=0.0007" answer different questions when the
	# result is being weighed as evidence rather than used as a gate.
	SCREENSHOT_STDDEV="$stddev"
	echo "==> Screenshot ${label} stddev=${stddev}"
	if awk -v s="$stddev" 'BEGIN{exit !(s > 0.02)}'; then
		return 0
	fi
	echo "==> Screenshot ${label} looks blank (stddev=${stddev} <= 0.02)" >&2
	return 1
}

# Give the display manager/desktop time to actually PAINT before the evidence
# screenshot. Under QEMU's plain virtio-vga there is no render node, so the
# guest composites with Mesa's llvmpipe software rasteriser; its first frame
# can trail the serial contract marker by a minute or more on a 2-4 vCPU
# runner (tunaOS#581). A fixed sleep before the screenshot therefore produced
# a black "10-ready" in the evidence gallery for an otherwise-healthy gate,
# and the screenshot-sanity fallback could not tell "slow" from "failed".
#
# Poll the framebuffer instead: screenshot, measure (screenshot_sane), retry
# until the image has structure or the cap is reached. The LAST screenshot is
# always left on disk as evidence. This is evidence, not a gate — pass/fail
# stays with the serial marker (the #575 mitigation) — so a machine that
# genuinely cannot paint extends the wait, it does not fail the run. The
# per-attempt stddev is logged so a blank result stays diagnosable.
wait_for_paint() {
	local label="$1"
	local cap="${TBOX_E2E_PAINT_TIMEOUT:-120}"
	local deadline=$(($(date +%s) + cap))
	local attempt=0
	while (($(date +%s) < deadline)); do
		attempt=$((attempt + 1))
		screenshot "$label"
		if screenshot_sane "$label"; then
			echo "==> ${label} painted on attempt ${attempt} (stddev=${SCREENSHOT_STDDEV:-unmeasured})"
			return 0
		fi
		sleep 15
	done
	# One final capture after the cap so the freshest frame is the evidence.
	screenshot "$label"
	if screenshot_sane "$label"; then
		return 0
	fi
	# :-unmeasured, not a bare expansion: screenshot_sane's early returns (no
	# ImageMagick, no capture) never set SCREENSHOT_STDDEV, and under set -u a
	# bare reference here killed the base Gate's TIMEOUT path before it could
	# print any diagnostics (sailfin run 32068513822, line-1323 crash).
	echo "==> ${label} still blank after ${cap}s (stddev=${SCREENSHOT_STDDEV:-unmeasured}) — the serial marker, not pixels, is the gate" >&2
	return 1
}
