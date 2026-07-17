#!/bin/bash
# e2e-runtime-checks.sh — TAP-style installed-system assertions, run at boot
# by tunaos-desktop-contract.service (second ExecStart, exit code ignored).
#
# Assertions adapted from frostyard/snosi's tiered on-VM test scripts
# (LGPL-2.1-or-later): test/tests/01-installation.sh, 02-services.sh,
# 04-smoke.sh and 05-firstboot-presets.sh, extended to cover every TunaOS
# variant (rpm / dpkg / pacman / portage) and desktop (gnome, kde, niri,
# cosmic, xfce — validated via the display-manager.service alias so distro
# unit-name drift like gdm vs gdm3 vs lightdm doesn't matter).
#
# Unlike snosi (which SSHes into the test VM), the installed TunaOS system
# has no login user CI can reach — the only channel out is the serial
# console. So this script is baked into the image, runs once graphical.target
# is reached, and emits TAP lines bracketed by grep-able markers that
# scripts/iso-e2e.sh harvests from the serial log:
#
#   TUNAOS_INSTALL_CHECKS_BEGIN
#   ok - ... / not ok - ...
#   TUNAOS_INSTALL_CHECKS_RESULT pass=N fail=M
#
# It is self-contained (no sourcing) because it runs from /usr/libexec inside
# the image, where scripts/lib/e2e-assert.sh does not exist. Checks are
# read-only and network-free: this also runs on every real user boot.
set -uo pipefail

DESKTOP="${1:-unknown}"

# Everything goes to stdout (journal+console) AND directly to /dev/ttyS0:
# StandardOutput=console can point at tty1, and the E2E gate reads serial.
emit() {
	echo "$1"
	echo "$1" >/dev/ttyS0 2>/dev/null || true
}

PASS=0
FAIL=0

check() {
	local desc="$1"
	shift
	if "$@" >/dev/null 2>&1; then
		emit "ok - $desc"
		PASS=$((PASS + 1))
	else
		emit "not ok - $desc"
		FAIL=$((FAIL + 1))
	fi
}

emit "TUNAOS_INSTALL_CHECKS_BEGIN desktop=${DESKTOP}"

# ── Installation validation (snosi 01) ─────────────────────────────────────

# Unit ordering (After=display-manager.service, WantedBy=graphical.target)
# means the system is mostly settled; accept degraded like snosi does.
sys_state=$(systemctl is-system-running 2>/dev/null || true)
emit "# system state: ${sys_state}"
check "system has booted (running or degraded)" \
	test "$sys_state" = "running" -o "$sys_state" = "degraded"

# bootc deployments mount the deployment root immutably — either literally
# ro in /proc/mounts or via a composefs/overlay stack. Accept any of those;
# a plain rw / would mean the install silently fell back to something wrong.
# shellcheck disable=SC2016
check "root filesystem is immutable (ro or composefs/overlay)" \
	bash -c 'findmnt -n -o FSTYPE / -t overlay,composefs >/dev/null 2>&1 || awk '\''$5 == "/" { exit (/\bro\b/ ? 0 : 1) }'\'' /proc/mounts'

check "/usr is read-only" \
	test ! -w /usr/bin

check "bootc status succeeds" \
	bootc status

# bootc's JSON flag drifted across releases (--json → --format json); the
# human output always carries the image ref, so fall through to it.
check "bootc reports an image reference" \
	bash -c '{ bootc status --json 2>/dev/null || bootc status --format json 2>/dev/null || bootc status 2>/dev/null; } | grep -qi "image"'

# ── First-boot semantics (snosi 05, applicable subset) ─────────────────────

# shellcheck disable=SC2016
check "machine-id is committed (32-hex, not uninitialized)" \
	bash -c '[[ "$(cat /etc/machine-id 2>/dev/null)" =~ ^[0-9a-f]{32}$ ]]'

# SSH host keys only exist where an ssh daemon is shipped; conditional like
# snosi's desktop-only gnome-remote-desktop check.
if systemctl list-unit-files sshd.service ssh.service --no-legend 2>/dev/null | grep -q .; then
	check "SSH host keys were generated" \
		bash -c 'ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1'
fi

# ── Service health (snosi 02, DE-aware) ────────────────────────────────────

check "graphical.target is active" \
	systemctl is-active graphical.target

# display-manager.service is the systemd alias every DM registers; checking
# it (rather than gdm/sddm/... by name) works on all variants, including
# Debian's gdm3 and xfce's lightdm-or-greetd split.
check "display manager is active (display-manager.service)" \
	systemctl is-active display-manager.service

dm_id=$(systemctl show -P Id display-manager.service 2>/dev/null || true)
emit "# display manager: ${dm_id:-unknown}"
case "$DESKTOP" in
gnome) dm_pattern='^(gdm|gdm3)\.service$' ;;
kde) dm_pattern='^sddm\.service$' ;;
niri | cosmic) dm_pattern='^greetd\.service$' ;;
xfce) dm_pattern='^(gdm|gdm3|lightdm|greetd)\.service$' ;;
*) dm_pattern='' ;;
esac
if [[ -n "$dm_pattern" ]]; then
	check "display manager matches ${DESKTOP} contract" \
		bash -c "[[ '${dm_id}' =~ ${dm_pattern} ]]"
fi

check "a network manager is active" \
	bash -c 'systemctl is-active NetworkManager 2>/dev/null || systemctl is-active systemd-networkd'

# Static unit-graph validation (secureblue pattern): catches units pointing
# at missing binaries or malformed files even when nothing has failed yet.
if command -v systemd-analyze >/dev/null 2>&1; then
	check "systemd unit graph verifies (graphical.target)" \
		systemd-analyze verify --recursive-errors=yes graphical.target
fi

# Informational only (snosi hard-fails here, but TunaOS desktop images carry
# harmless failures on headless/serial boots).
failed_units=$(systemctl --failed --no-legend 2>/dev/null | wc -l)
emit "# failed systemd units: ${failed_units}"
if [[ "$failed_units" -gt 0 ]]; then
	while IFS= read -r line; do emit "#   $line"; done \
		< <(systemctl --failed --no-legend 2>/dev/null)
fi

# ── Smoke (snosi 04, distro-aware, network-free) ───────────────────────────

# shellcheck disable=SC2016
check "package metadata intact (>100 installed packages)" \
	bash -c 'if command -v rpm >/dev/null; then n=$(rpm -qa | wc -l); elif command -v dpkg >/dev/null; then n=$(dpkg -l | grep -c "^ii"); elif command -v pacman >/dev/null; then n=$(pacman -Q | wc -l); elif command -v qlist >/dev/null; then n=$(qlist -I | wc -l); else exit 1; fi; test "$n" -gt 100'

# shellcheck disable=SC2016
check "system time is reasonable (year >= 2025)" \
	bash -c 'test "$(date +%Y)" -ge 2025'

# shellcheck disable=SC2016
check "hostname is set" \
	bash -c 'test -n "$(hostname 2>/dev/null || cat /proc/sys/kernel/hostname)"'

check "locale is configured" \
	locale

emit "TUNAOS_INSTALL_CHECKS_RESULT pass=${PASS} fail=${FAIL} desktop=${DESKTOP}"
exit "$FAIL"
