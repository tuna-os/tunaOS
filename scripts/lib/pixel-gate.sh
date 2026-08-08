#!/usr/bin/env bash
# pixel-gate.sh — decide whether the installed system PROVABLY drew pixels.
#
# Sourced by scripts/iso-e2e.sh; a separate lib file so bats can source the
# real logic (tests/bats/test_pixel_gate.bats) instead of grepping for it.
#
# WHY. The strongest runtime gate on the installed system used to be
# "display-manager.service is active", and the repo's own history shows that
# passing over a black console (run 29645108966). The evidence to contradict
# it has been captured all along — the timelapse recorder screendumps real
# frames on every GPU-less runner (151-210 frames on passing cells) and the
# installed-desktop screenshot is stddev-measured — but both were recorded
# fatal=0 and gated nothing. This turns the measurable cases into a gate and
# names the unmeasurable ones instead of silently passing them.
#
# pixel_gate <shot> <stddev> <frames> <virgl>
#   shot    drawn | blank | unmeasured | absent — screenshot_sane's verdict
#           on the installed-desktop capture (iso-e2e.sh computes it)
#   stddev  the measured grayscale stddev, or empty when not measured
#   frames  content of the timelapse frame-count.txt, or empty when absent
#   virgl   1 when QEMU runs GL scanout (egl-headless), else 0
#
# Prints exactly one evidence line:
#   TUNAOS_LUKS_E2E_PIXEL_GATE result=<r> frames=<n> stddev=<s> fatal=<0|1>
# Returns 0 when the gate passes or is advisory, 1 on a fatal failure.
#
# The decision table, and why each row is what it is:
#   virgl=1        → skipped_virgl, advisory. screendump answers "no surface"
#                    under GL scanout (see iso-e2e.sh's screenshot() comment)
#                    so neither frames nor the capture measure anything here.
#                    Saying skipped beats a silent pass.
#   shot=unmeasured→ unmeasured, advisory. A capture exists but ImageMagick
#                    was absent, so no verdict was measured — recording that
#                    refusal as "blank" would invent a product failure out of
#                    a missing host package (iso-e2e.sh already refuses to).
#   frames=0/empty → no_frames, FATAL. On the plain (non-virgl) path the
#                    recorder uses the same monitor socket as the screenshot;
#                    zero frames across an entire install means the one
#                    channel that can contradict "DM active" never worked,
#                    and an unverifiable cell must not be a green cell.
#   shot=drawn     → pass, FATAL gate satisfied: something actually rendered.
#   shot=blank     → blank, FATAL failure — this is the black console that
#                    used to ship. The stddev rides along as the measurement.
#   shot=absent    → absent, FATAL failure: on the plain path screendump
#                    works whenever QEMU is alive, so no capture at all means
#                    the surface was never there to photograph.
#
# `drawn` still only means SOMETHING rendered — a greeter that draws, or a
# text login, clears the same stddev floor; the greeter-drew-but-no-session
# hole stays open and documented (iso-e2e.sh). This gate closes the
# black-console hole, which is the one that has actually shipped.
pixel_gate() {
	local shot="$1" stddev="$2" frames="$3" virgl="$4"
	local result fatal rc

	if [[ "$virgl" == "1" ]]; then
		result="skipped_virgl" fatal=0 rc=0
	elif [[ "$shot" == "unmeasured" ]]; then
		result="unmeasured" fatal=0 rc=0
	elif [[ -z "$frames" || "$frames" == "0" ]]; then
		result="no_frames" fatal=1 rc=1
	elif [[ "$shot" == "drawn" ]]; then
		result="pass" fatal=1 rc=0
	elif [[ "$shot" == "blank" ]]; then
		result="blank" fatal=1 rc=1
	else
		result="absent" fatal=1 rc=1
	fi

	echo "TUNAOS_LUKS_E2E_PIXEL_GATE result=${result} frames=${frames:-0} stddev=${stddev:-na} fatal=${fatal}"
	return "$rc"
}
