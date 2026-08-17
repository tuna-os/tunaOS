#!/usr/bin/env bash
# verify-base-contract.sh — the base image's boot contract (green criterion 3
# for `base` cells).
#
# Desktop cells prove themselves with tunaos-desktop-contract.service emitting
# TUNAOS_DESKTOP_CONTRACT_OK on the serial console at graphical.target. Base
# cells had no equivalent, so the Gate skipped them entirely and "base boots"
# was asserted by nothing (GREEN-MASTER-PLAN W3: the absence of a gate looks
# like success). This is the base-cell marker: it runs at multi-user.target
# and proves the two things a headless bootc image must do — come up, and be
# an operable bootc deployment.
#
# What FAILS the contract (deliberately narrow — variants legitimately differ
# in unit sets, so "zero degraded units" would be flaky theater):
#   * the system lands in `maintenance`/`offline`/`starting` after the wait —
#     it never actually reached multi-user
#   * `bootc status` cannot report a booted deployment — the thing that makes
#     the image updatable/rollbackable is broken, which for a bootc OS is the
#     product (criterion 6's reasoning)
# Degraded is reported in the marker but does not fail: which units are
# allowed to fail is per-variant knowledge that belongs in richer contracts,
# not this boot gate.
#
# Runs with --runtime under the systemd unit; without it (build time) it only
# sanity-checks that bootc exists in the image so a broken install fails the
# build, not the boot.

set -uo pipefail

fail() {
	echo "TUNAOS_BASE_CONTRACT_FAIL reason=$1" >&2
	exit 1
}

if [[ "${1:-}" != "--runtime" ]]; then
	command -v bootc >/dev/null 2>&1 || fail "bootc-missing-at-build"
	echo "TUNAOS_BASE_CONTRACT_BUILDCHECK_OK"
	exit 0
fi

# --wait blocks until startup settles, so a slow unit cannot race this check
# into a false `starting` verdict on a 2-vCPU runner.
state=$(systemctl is-system-running --wait 2>/dev/null || true)
case "$state" in
running | degraded) ;;
*) fail "system-state=${state:-unknown}" ;;
esac

if ! bootc status >/dev/null 2>&1; then
	fail "bootc-status-failed"
fi

echo "TUNAOS_BASE_CONTRACT_OK state=${state}"
