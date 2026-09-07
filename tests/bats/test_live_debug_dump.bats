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
# Three properties are worth pinning:
#   1. It is DEV-ONLY. Production ISOs must not ship a service that dumps
#      journals to the console.
#   2. Nothing in the boot can gate it. The first version ordered it
#      After=tunaos-live-ready.service — and on a boot where the session never
#      started, that unit had not emitted its marker minutes in (it waits on
#      NetworkManager-wait-online.service, 90s default), so the diagnostic was
#      silent in the one case it exists for. It is timer-driven now.
#   3. It writes to /dev/ttyS0, not to /dev/console: under -display none those
#      are not the same device, and only the former is in the serial log.

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

@test "the diagnostics timer is enabled" {
	dev_block | grep -q 'systemctl enable tunaos-live-debug.timer'
}

@test "the embedded script is valid bash" {
	debug_script | bash -n
}

@test "the dump is ordered behind nothing that can gate it" {
	# MEASURED: on a marlin:kde boot where the live session never started,
	# tunaos-live-ready.service had not emitted its marker minutes in — it is
	# After=NetworkManager-wait-online.service, a 90s default timeout. A
	# diagnostic ordered behind that unit is silent in exactly the failure it
	# exists to explain, which is the trap
	# test_live_ready_net_diagnostic.bats records for the net diagnostic.
	! dev_block | grep -q 'After=tunaos-live-ready.service'
	! dev_block | grep -q 'Wants=tunaos-live-ready.service'
	# A timer, not a target, so nothing in the boot transaction gates it.
	dev_block | grep -q 'OnBootSec='
}

@test "the dump reaches the serial port the harness captures" {
	# NOT journal+console: in headless QEMU (-display none) /dev/console is
	# not the serial port, which is why tunaos-live-ready.service writes to
	# /dev/ttyS0 directly. A console-routed dump would never reach the serial
	# log the harness uploads.
	dev_block | grep -q 'StandardOutput=tty'
	dev_block | grep -q 'TTYPath=/dev/ttyS0'
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

@test "the live squash never blocks its desktop on flatpak-preinstall" {
	# MEASURED from the guest's own diagnostics at 40s on a marlin:kde dev
	# ISO: flatpak-preinstall.service was 'start running' with
	# multi-user.target, graphical.target AND tunaos-live-ready.service all
	# 'start waiting' behind it. Type=oneshot + WantedBy=multi-user.target
	# means the target waits for the download to finish, so the live desktop
	# never starts. Masked for live media only; installed systems still get
	# the curated app set from build_scripts/desktop/flatpak-preinstall.sh.
	grep -q 'systemctl mask flatpak-preinstall.service' "$CUSTOMIZE"
	# ...and NOT inside the dev-only block: a production live ISO stalls the
	# same way, and its users have no serial log to explain it.
	! dev_block | grep -q 'flatpak-preinstall'
}
