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
#   * the system has landed somewhere broken — `maintenance` (emergency or
#     rescue), `stopping`, `offline`, or a state we cannot read at all
#   * `bootc status` cannot report a booted deployment — the thing that makes
#     the image updatable/rollbackable is broken, which for a bootc OS is the
#     product (criterion 6's reasoning)
# Degraded is reported in the marker but does not fail: which units are
# allowed to fail is per-variant knowledge that belongs in richer contracts,
# not this boot gate. Neither does `starting`: this unit is itself a job in
# the boot transaction, so `starting` describes the contract rather than the
# image — see the long note at the state sample below.
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

# ── System state, sampled once and never waited on ──────────────────────────
#
# This was `systemctl is-system-running --wait`, on the reasoning that a slow
# unit must not race the check into a false `starting` verdict. The wait
# cannot work from here, and the reason is structural rather than a matter of
# how long it waits:
#
#   * `--wait` returns when the manager leaves `starting`.
#   * The manager leaves `starting` when the initial transaction drains.
#   * This unit is a job IN that transaction — WantedBy=multi-user.target —
#     and a Type=oneshot job stays running until its ExecStart exits.
#
# So the check waited on the transaction that was waiting on the check.
# MEASURED to microsecond resolution in tunaOS#2514: `Startup finished` was
# logged 10-14ms AFTER this unit exited, on two runs at two different bounds,
# and the reported userspace settle time tracked the bound rather than the
# image (120s bound -> "2min 7s"; 240s bound -> "4min 7s").
#
# The cost was the whole contract. On base cells the wait ran until
# TimeoutStartSec=300 killed the unit; on desktop cells the harness saw the
# desktop marker and powered the VM off mid-wait
# (`code=killed, status=15/TERM`, no verdict either way). Every check below
# this line — the `bootc status` assertion that is the actual point of a bootc
# boot contract — was unreachable on every cell in the matrix.
#
# This is the FIFTH instance of one shape in this tree (docs/ci-troubleshooting.md
# rows 29, 33, 35, 42, 43); `checks/e2e-runtime-checks.sh` carries the
# reviewed fix and this now matches it exactly. Sample once, and assert the
# half that does not depend on WHEN we sample: that the boot has not landed
# somewhere broken. `maintenance` (emergency/rescue), `stopping`, `offline`
# and an unreadable state are real defects whenever you ask.
# `starting`/`initializing` are what a healthy in-transaction sample looks
# like — and this unit runs After=multi-user.target, so reaching it at all
# already proves multi-user was reached. `running`/`degraded` are a healthy
# settled sample, which is what a desktop cell's later poweroff usually
# produces.
state=$(systemctl is-system-running 2>/dev/null || true)
case "${state:-unknown}" in
running | degraded | initializing | starting) ;;
*) fail "system-state=${state:-unknown}" ;;
esac

# `degraded` is deliberately allowed above — which units a variant may fail is
# per-variant knowledge that does not belong in a boot gate. But "degraded"
# with no names is not something anyone can act on, and this marker is the
# only per-boot health evidence a base cell puts on the serial console. Name
# them, as evidence; never as a verdict. Guarded: a diagnostic must not be
# what fails a contract.
failed_units=$(systemctl list-units --state=failed --no-legend --plain 2>/dev/null |
	awk '{ print $1 }' | paste -sd, - 2>/dev/null) || failed_units=""
echo "TUNAOS_BASE_CONTRACT_NOTE state=${state:-unknown} failed-units=${failed_units:-none}" >&2

if ! bootc status >/dev/null 2>&1; then
	fail "bootc-status-failed"
fi

echo "TUNAOS_BASE_CONTRACT_OK state=${state}"
