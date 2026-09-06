#!/usr/bin/env bats
# The dev ISO's self-diagnostics: tunaos-live-debug.service.
#
# It exists because of a failure nothing else could explain. marlin:kde
# reaches TUNAOS_LIVE_READY with graphical.target inactive and a framebuffer
# measuring EXACTLY 0 — the session never starts — and the artifact that would
# name the cause (`journalctl -u sddm`) needs a shell in the guest. On that
# variant there is no shell to be had: sshd accepts and immediately closes over
# both TCP and vsock, and scripts/iso-e2e.sh attaches the serial as a
# write-only file, so the text login on ttyS0 cannot be answered either. The
# guest therefore reports on itself, to the console, which is the serial log
# the harness already captures.
#
# Two properties are worth pinning:
#   1. It is DEV-ONLY. Production ISOs must not ship a service that dumps
#      journals to the console.
#   2. It runs AFTER the readiness marker, so it can neither gate a run nor
#      slow one down.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CUSTOMIZE="${REPO_ROOT}/live-iso/common/src/customize-live.sh"

# The dev-only block starts at the .enable-sshd marker test. Everything the
# diagnostics install does must sit inside it.
dev_block() {
	sed -n '/if \[\[ -f "${SCRIPT_DIR}\/.enable-sshd" \]\]; then/,/^fi$/p' "$CUSTOMIZE"
}

# The script body written into /usr/libexec/tunaos-live-debug.
debug_script() {
	sed -n "/cat >\/usr\/libexec\/tunaos-live-debug <<'DBGEOF'/,/^DBGEOF$/p" "$CUSTOMIZE" |
		sed '1d;$d'
}

@test "the diagnostics service is installed only on dev ISOs" {
	# Present in the file at all...
	grep -q 'tunaos-live-debug.service' "$CUSTOMIZE"
	# ...and every mention of it is inside the .enable-sshd block. A copy
	# outside would ship journal dumps on production media.
	local total in_block
	total=$(grep -c 'tunaos-live-debug' "$CUSTOMIZE")
	in_block=$(dev_block | grep -c 'tunaos-live-debug')
	[ "$total" -eq "$in_block" ]
}

@test "the diagnostics service is enabled" {
	dev_block | grep -q 'systemctl enable tunaos-live-debug.service'
}

@test "the embedded script is valid bash" {
	debug_script | bash -n
}

@test "the dump runs after the readiness marker, never before it" {
	# After= alone would let it run when the marker unit is not pulled in at
	# all; the point is ordering, and Wants= keeps the ordering meaningful.
	dev_block | grep -q 'After=tunaos-live-ready.service'
	# It must not be ordered BEFORE anything the harness gates on.
	! dev_block | grep -q 'Before=tunaos-live-ready.service'
}

@test "the dump reaches the console, not only the journal" {
	# The serial log IS the console. A journal-only dump would be invisible
	# to every artifact the harness uploads — the exact failure mode
	# test_live_ready_net_diagnostic.bats records for the net diagnostic.
	dev_block | grep -q 'StandardOutput=journal+console'
	dev_block | grep -q 'StandardError=journal+console'
}

@test "the dump is fenced with greppable markers" {
	# scripts/iso-e2e.sh's dump_live_debug_sections extracts the block with
	# these two markers; renaming one without the other silently empties the
	# job-log output.
	debug_script | grep -q 'TUNAOS_LIVE_DEBUG_START'
	debug_script | grep -q 'TUNAOS_LIVE_DEBUG_DONE'
	grep -q 'TUNAOS_LIVE_DEBUG_START' "${REPO_ROOT}/scripts/iso-e2e.sh"
	grep -q 'TUNAOS_LIVE_DEBUG_DONE' "${REPO_ROOT}/scripts/iso-e2e.sh"
}

@test "the dump covers the display manager of every desktop we ship" {
	# The unit name differs per desktop and a missing one means a silent gap
	# exactly where that desktop's session failure would have been explained.
	local script
	script="$(debug_script)"
	for dm in sddm plasmalogin gdm greetd lightdm cosmic-greeter; do
		echo "$script" | grep -q "$dm"
	done
}

@test "the dump covers sshd, the harness's own way in" {
	local script
	script="$(debug_script)"
	echo "$script" | grep -q 'ssh-journal'
	echo "$script" | grep -q 'ssh-listeners'
}

@test "a missing unit or command cannot abort the remaining sections" {
	# set -e here would mean the first absent display manager truncates the
	# dump — and the sections that matter are the ones after it.
	local script
	script="$(debug_script)"
	! echo "$script" | grep -qE '^set -e|^set -eu|^set -euo'
	echo "$script" | grep -qE '^set -u$'
}
