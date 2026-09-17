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
#   * the system message bus is not running — see below
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

# ── SELinux state, printed BEFORE anything can block ────────────────────────
#
# tunaOS#2485: dbus-broker, systemd-logind and pam_selinux all fail on the two
# rolling EL10 bases, and all three fail inside libselinux:
#
#   dbus-broker-launch: Access denied in /etc/selinux/targeted/contexts/dbus_contexts +1
#   systemd-logind: Failed to initialize SELinux labeling handle: Permission denied
#   sshd-session: pam_selinux(sshd:session): Unable to get valid context for root
#
# The images are identical where the issue looked: dbus_contexts is byte-for-byte
# the same as albacore's, 0644 root:root, and no image in the family carries a
# security.selinux xattr at all. So the labels arrive at install time, and the
# question is what they are on the running machine — which nobody has seen,
# because the gate collects diagnostics over SSH and sshd cannot open a PAM
# session without the bus. The one image that could answer is the one that
# cannot be asked.
#
# Serial answers it. This dump goes to the console through the unit's
# StandardOutput=journal+console, so it survives a machine with no working bus,
# no logind and no SSH.
#
# It sits ABOVE the settle wait deliberately. Everything below that wait is
# unreachable on exactly the images this exists to describe (tunaOS#2514), and
# evidence that only prints on healthy machines is not evidence.
#
# Every command is guarded. A diagnostic must never be the reason a contract
# fails, and `set -e` is off here precisely so a missing tool stays a missing
# line.
# One field of the probe. Run the command, fall back to a single word on any
# failure, and reject a value with whitespace in it.
#
# The fallback has to survive more than a missing binary. `rpm -q` prints
# "package X is not installed" on STDOUT and exits 1, so `2>/dev/null` does not
# silence it and the text lands inside the marker. CI caught precisely that,
# through this probe's own test:
#
#   stray line in probe output: 'unknown policy=package selinux-policy is not installed'
#
# One field became three lines and none of them was a measurement. Assign,
# overwrite on a non-zero exit, then refuse anything that is not one bare word.
_selinux_field() {
	local fallback=$1
	shift
	local out
	out=$("$@" 2>/dev/null) || out="${fallback}"
	[[ -n "${out}" && "${out}" != *[[:space:]]* ]] || out="${fallback}"
	printf '%s' "${out}"
}

_selinux_probe() {
	local ctx=/etc/selinux/targeted/contexts/dbus_contexts

	# matchpathcon opens the same file_contexts handle that logind and
	# dbus-broker open. `lookup-failed` here IS the tunaOS#2485 symptom,
	# reported by the one tool that can still speak. Kept distinct from
	# `unavailable`, which only means the tool is absent.
	local expected=unavailable
	if command -v matchpathcon >/dev/null 2>&1; then
		expected=$(_selinux_field lookup-failed matchpathcon -n "${ctx}")
	fi

	echo "TUNAOS_SELINUX_PROBE" \
		"enforce=$(_selinux_field unknown getenforce)" \
		"lib=$(_selinux_field unknown rpm -q --qf '%{VERSION}-%{RELEASE}' libselinux)" \
		"policy=$(_selinux_field unknown rpm -q --qf '%{VERSION}-%{RELEASE}' selinux-policy)"
	# stat -c %C, not ls -Z: it prints the context alone, and parsing ls output
	# is a habit worth not having.
	echo "TUNAOS_SELINUX_PROBE label=$(_selinux_field unreadable stat -c '%C' "${ctx}")"
	echo "TUNAOS_SELINUX_PROBE dir=$(_selinux_field unreadable stat -c '%C' "${ctx%/*}")"
	echo "TUNAOS_SELINUX_PROBE expected=${expected}"
	echo "TUNAOS_SELINUX_PROBE readable=$([[ -r ${ctx} ]] && echo yes || echo no)"
}
_selinux_probe 2>&1 || true

# --wait blocks until startup settles, so a slow unit cannot race this check
# into a false `starting` verdict on a 2-vCPU runner. BOUND it, though: --wait
# waits for a terminal state, and a machine whose startup never settles never
# supplies one. skipjack:gnome hung here for the unit's full 300s
# TimeoutStartSec and was killed without printing a single line:
#
#   Starting tunaos-base-contract.service - Verify TunaOS base boot contract...
#   [ 314.604325] tunaos-base-contract.service: start operation timed out. Terminating.
#   [ 314.635751] Failed to start tunaos-base-contract.service
#
# (run 34760890405, and identically in 34705564876 before the bus assertion
# below existed — so the hang is older than that check, not caused by it.)
#
# Two things were lost to that. The gate reported "timeout" where the machine
# had a specific, nameable defect, and every check BELOW this line became
# unreachable on precisely the images they exist to judge — including the
# system-bus assertion, which was written for this exact failure and has never
# once been able to fire on it.
#
# So: bound the wait, then fall back to an unblocking query. Asking again
# without --wait turns a silent kill into a named verdict and lets the rest of
# the contract run.
#
# The bound was 120s and that was far too tight. hummingbird:gnome takes
# 2min 7s of userspace to settle, and run 34775725935 caught the bound
# expiring FOURTEEN MILLISECONDS before the machine became healthy:
#
#   [ 133.320660 ] TUNAOS_BASE_CONTRACT_NOTE settle-wait-timed-out state=starting
#   [ 133.334844 ] Startup finished in 1.159s (kernel) + 5.100s (initrd)
#                  + 2min 7.074s (userspace) = 2min 13.334s
#
# A contract that fails an image which was about to pass is worse than no
# contract. The unit allows TimeoutStartSec=300 (40-services.sh) and starts
# after multi-user.target at roughly 13s, so 240s leaves about 60s for the
# checks below to run and print a verdict before systemd kills the service.
# That is nearly double the slowest settle measured, and still bounded.
#
# Overridable so the tests can use a short bound instead of two minutes of
# real time; nothing in the image sets it.
: "${TUNAOS_SETTLE_WAIT_SECONDS:=240}"

# Only exit 124 — timeout(1)'s own code — means the wait ran out. `degraded`
# is an ALLOWED state here and `is-system-running` exits non-zero for it, so a
# bare `if !` would have called every degraded boot a hang.
_settle_rc=0
state=$(timeout "${TUNAOS_SETTLE_WAIT_SECONDS}s" systemctl is-system-running --wait 2>/dev/null) || _settle_rc=$?
if [[ ${_settle_rc} -eq 124 ]]; then
	state=$(systemctl is-system-running 2>/dev/null || true)
	echo "TUNAOS_BASE_CONTRACT_NOTE settle-wait-timed-out state=${state:-unknown}" >&2
fi
case "$state" in
running | degraded) ;;
*) fail "system-state=${state:-unknown}" ;;
esac

if ! bootc status >/dev/null 2>&1; then
	fail "bootc-status-failed"
fi

# The system message bus. This is as narrow as the two checks above and for the
# same reason: it is not a per-variant unit-set opinion, it is whether the
# machine is operable at all. logind, polkit, NetworkManager, upower and every
# display manager reach the session through it, so an image without it is not a
# degraded desktop, it is a shell prompt with no way to log in graphically.
#
# It is asserted here because `degraded` is deliberately allowed above, and a
# dead bus hides inside `degraded` on some images while failing the whole boot
# on others. Measured 2026-09-12, skipjack run 34705564876:
#
#   gnome: dbus-broker died 5 times on
#            Access denied in /etc/selinux/targeted/contexts/dbus_contexts +1
#          -> dbus.socket: Failed with result 'service-start-limit-hit'
#          -> Dependency failed for gdm.service            -> Gate RED
#   kde:   the identical failure, 8 restarts, same start-limit
#          -> its desktop contract marker was emitted anyway -> Gate GREEN
#
# So skipjack:kde promoted an image with no system bus, and `boots` said yes.
# That is the case this closes: the same broken machine now fails both cells
# instead of one. albacore, built from the same pipeline on a non-rolling EL10
# base, starts the bus cleanly (run 34726078460) -- so this is a real defect
# being reported, not a bar nothing can clear.
#
# The unit is resolved rather than hardcoded: `dbus.service` is an alias, and
# which implementation it points at (dbus-broker, dbus-daemon) is exactly the
# per-variant detail this check must not care about.
bus_unit=$(systemctl show -P Id dbus.service 2>/dev/null || true)
bus_unit="${bus_unit:-dbus.service}"
if ! systemctl is-active --quiet "$bus_unit"; then
	fail "system-bus-inactive unit=${bus_unit} state=$(systemctl is-active "$bus_unit" 2>/dev/null || echo unknown)"
fi

echo "TUNAOS_BASE_CONTRACT_OK state=${state} bus=${bus_unit}"
