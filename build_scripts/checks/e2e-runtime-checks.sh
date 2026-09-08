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

# SSH host keys only exist where an ssh daemon actually RUNS -- not merely
# where one is shipped.
#
# The guard used to be `list-unit-files sshd.service ssh.service`, which
# matches a unit that is present but DISABLED. Production images ship openssh
# and then deliberately turn it off (see the safe_disable calls in
# 40-services.sh), so sshd-keygen never runs and /etc/ssh/ssh_host_*_key
# legitimately does not exist. The assertion was therefore red on every
# installed system, on every flavor -- MEASURED on all five marlin flavors at
# ~11s, each on a LUKS install that otherwise passed end to end.
#
# That is the third assertion in this file found permanently red for a reason
# unrelated to what it claims to test (see also graphical.target and the
# unit-graph gate). A check that always says the same thing cannot report a
# regression.
#
# Gating on enabled-or-active keeps it meaningful exactly where it matters:
# the dev ISOs, where ENABLE_SSHD=1 and the e2e harness's only way into the
# guest is that daemon.
_sshd_on=0
for _u in sshd.service ssh.service sshd.socket ssh.socket; do
	if systemctl is-enabled "$_u" &>/dev/null || systemctl is-active "$_u" &>/dev/null; then
		_sshd_on=1
		break
	fi
done
if [[ "$_sshd_on" -eq 1 ]]; then
	check "SSH host keys were generated" \
		bash -c 'ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1'

	# Host keys existing, and the unit reporting Started, do not add up to
	# "the daemon is REACHABLE" — and when it isn't, the serial log is the
	# only channel out, so whatever it doesn't say is unknowable after the
	# fact. guppy:xfce fails the LUKS gate at "Connection timed out during
	# banner exchange" (runs 31101520694, 31101896534) having logged
	# "Started OpenSSH server daemon", no failed unit, and a passing
	# "a network manager is active" — evidence that is equally consistent
	# with the guest holding no address and with nothing bound to :22. The
	# serial cannot currently tell those apart, so a diagnosis from it is a
	# guess. These two lines make it tell.
	#
	# Informational, not assertions: a production image legitimately ships
	# sshd off with nothing listening, and this script runs on every real
	# user boot. Both reads are local — no packets — so they stay inside
	# this file's "read-only and network-free" contract.
	if command -v ip >/dev/null 2>&1; then
		emit "# ipv4: $(ip -brief -4 addr show scope global 2>/dev/null | tr '\n' ';')"
	else
		emit "# ipv4: ip(8) unavailable"
	fi
	# Report the failure rather than an empty string when ss is absent: a
	# blank listener list reads as "nothing is listening", which is the very
	# conclusion this line exists to establish.
	if command -v ss >/dev/null 2>&1; then
		emit "# tcp listeners: $(ss -H -ltn 2>/dev/null | awk '{print $4}' | sort -u | tr '\n' ' ')"
	else
		emit "# tcp listeners: ss(8) unavailable"
	fi
else
	# Say so rather than skipping in silence. A production image with sshd off
	# and a DEV ISO whose sshd failed to enable both end up with no host keys;
	# only this line separates them in the serial log, and the dev case is the
	# one that costs the harness its only way into the guest.
	emit "# ssh: no sshd/ssh unit enabled or active — host-key check skipped"
fi
unset _sshd_on _u

# ── Service health (snosi 02, DE-aware) ────────────────────────────────────

# NOT `is-active graphical.target`. This script runs from
# tunaos-desktop-contract.service, which is WantedBy=graphical.target — so it
# executes INSIDE that target's own startup transaction, and a target is not
# `active` until every unit wanting it has finished. `is-active` therefore
# reports `activating` here and structurally always will: the assertion said
# `not ok` on every desktop, on every run, including runs that passed
# end-to-end (measured on marlin:cosmic at 11.7s under greetd AND on
# marlin:kde at 12.4s under sddm, both LUKS installs that otherwise passed).
#
# A permanently-red assertion can never report a real regression, which is the
# same defect as the installer GUI gate that could neither pass nor fail.
#
# Note the trap in the obvious fix: polling until `active` would DEADLOCK.
# The target waits on this unit and this unit would wait on the target, until
# TimeoutStartSec=90 killed it — a 90-second stall added to every boot.
graphical_state=$(systemctl show -P ActiveState graphical.target 2>/dev/null || echo unknown)
emit "# graphical.target ActiveState: ${graphical_state} (activating is correct from inside its own transaction)"
# MEASURED on a marlin:niri installed boot: ActiveState was `inactive` at
# 10.9s with `system state: starting` -- a perfectly healthy system, checked
# before graphical.target had even been queued. So ActiveState cannot separate
# healthy from broken here AT ANY TOLERANCE: accepting `inactive` would make
# the assertion vacuous, and rejecting it fails good boots. Its value depends
# on when this unit happens to be sampled, which this unit cannot control.
#
# `is-failed` does not have that problem. It is true only when the target
# actually failed, whenever you ask -- so it still catches a real regression
# without going red on a system that is merely still starting.
#
# The claim "this is a graphical system" is already carried, more reliably, by
# the default-target assertion below plus the two display-manager assertions.
check "graphical.target has not failed" \
	bash -c '! systemctl is-failed --quiet graphical.target'

# The stable half of the original intent: is this actually a graphical system?
# Unlike ActiveState, get-default does not depend on when in the boot we ask.
check "graphical.target is the default target" \
	bash -c '[[ "$(systemctl get-default 2>/dev/null)" == graphical.target ]]'

# display-manager.service is the systemd alias every DM registers; checking
# it (rather than gdm/sddm/... by name) works on all variants, including
# Debian's gdm3 and xfce's lightdm-or-greetd split.
check "display manager is active (display-manager.service)" \
	systemctl is-active display-manager.service

dm_id=$(systemctl show -P Id display-manager.service 2>/dev/null || true)
emit "# display manager: ${dm_id:-unknown}"
case "$DESKTOP" in
gnome) dm_pattern='^(gdm|gdm3)\.service$' ;;
kde) dm_pattern='^(sddm|plasmalogin)\.service$' ;; # KDE 6.5+ renamed sddm
niri) dm_pattern='^greetd\.service$' ;;
# cosmic-greeter IS greetd (ExecStart=greetd --config
# /etc/greetd/cosmic-greeter.toml), and on Ubuntu its postinst owns the
# display-manager.service alias, so dm_id is cosmic-greeter there and greetd on
# Fedora/EL10. Both are the same greeter.
cosmic) dm_pattern='^(greetd|cosmic-greeter)\.service$' ;;
xfce) dm_pattern='^(gdm|gdm3|lightdm|greetd)\.service$' ;;
*) dm_pattern='' ;;
esac
if [[ -n "$dm_pattern" ]]; then
	check "display manager matches ${DESKTOP} contract" \
		bash -c "[[ '${dm_id}' =~ ${dm_pattern} ]]"
fi

# greetd active is NOT the same as greetd usable. Its stock config runs
# `agreety --cmd /bin/sh` — a text prompt into a bare shell, with no session
# picker and no way to reach the desktop. That state still satisfies every
# check above: graphical.target is active, display-manager.service is active,
# and the DM matches the contract. XFCE shipped exactly this until gtkgreet
# was packaged, and nothing here caught it.
#
# So when greetd is the DM, assert its configured session is a real greeter.
#
# Scoped to xfce deliberately. cosmic-greeter ships /etc/greetd/
# cosmic-greeter.toml (plus its own cosmic-greeter.service) rather than
# config.toml, so reading config.toml on cosmic/niri would test a file their
# greeter does not use and fail two currently-green flavors. Extending this to
# them needs their real config path confirmed first — see tunaOS#636.
if [[ "$dm_id" == "greetd.service" && "$DESKTOP" == "xfce" ]]; then
	greetd_cmd=$(sed -n '/^\[default_session\]/,/^\[/p' /etc/greetd/config.toml 2>/dev/null |
		sed -n 's/^[[:space:]]*command[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' | head -1)
	emit "# greetd session command: ${greetd_cmd:-<none>}"
	check "greetd launches a graphical greeter (not agreety/shell)" \
		bash -c "[[ -n '${greetd_cmd}' ]] && [[ ! '${greetd_cmd}' =~ agreety ]]"
	# The command is run by greetd, so a typo'd or unpackaged greeter binary
	# fails at login with nothing in the image to show for it.
	greetd_bin=${greetd_cmd%% *}
	if [[ -n "$greetd_bin" ]]; then
		check "greetd session binary exists (${greetd_bin})" \
			command -v "$greetd_bin"
	fi
fi

check "a network manager is active" \
	bash -c 'systemctl is-active NetworkManager 2>/dev/null || systemctl is-active systemd-networkd'

# Static unit-graph validation (secureblue pattern): catches units pointing
# at missing binaries or malformed files even when nothing has failed yet.
if command -v systemd-analyze >/dev/null 2>&1; then
	# --recursive-errors=no, NOT yes. With `yes`, a warning in ANY
	# transitively reachable unit fails the check — including upstream units
	# we do not ship and cannot fix. Measured on this very repo's dev host:
	# `--recursive-errors=yes graphical.target` reports
	# "flatpak-appstream-refresh.service:7: Unknown key 'ExecCondition'",
	# an upstream packaging nit, and that alone is enough to fail it. So this
	# assertion was red on every desktop on every run, which is the same
	# always-says-the-same-thing defect as the check above.
	#
	# `no` verifies graphical.target itself, which is the unit we control and
	# the thing this gate is actually claiming. The transitive sweep is still
	# run, but as INFORMATION — its warnings are worth reading and are not
	# worth failing a build over, and printing them beats the previous
	# behaviour of discarding the output into /dev/null.
	# --man=no because bootc images strip man pages, and systemd-analyze's
	# man-page EXISTENCE check then fails with "'(man)' failed with exit
	# status 1" -- measured on a marlin:niri installed system, where it was
	# enough on its own to keep this gate red even after --recursive-errors=no
	# removed the upstream-unit noise. A missing man page is not a unit defect.
	check "systemd unit graph verifies (graphical.target)" \
		systemd-analyze verify --man=no --recursive-errors=no graphical.target
	analyze_warnings=$(systemd-analyze verify --man=no --recursive-errors=yes graphical.target 2>&1 || true)
	if [[ -n "$analyze_warnings" ]]; then
		emit "# systemd-analyze warnings across the graphical.target graph (informational):"
		while IFS= read -r line; do emit "#   $line"; done <<<"$analyze_warnings"
	fi
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

# Tell an automated reader where to go next. These checks run on the guest's
# serial console, which is the ONLY channel out of an installed system that
# ships no sshd -- so whatever this does not print is unknowable after the
# fact. Naming the artifacts here saves the next agent rediscovering them.
if [[ "$FAIL" -gt 0 ]]; then
	emit "# AGENT: ${FAIL} assertion(s) failed on the INSTALLED system."
	emit "# AGENT: this output is the guest serial console; the host copy is"
	emit "#        <output-dir>/installed-serial.log (or serial.log for the live boot)."
	emit "# AGENT: re-read the '# ' info lines above — they carry the measured"
	emit "#        values (display manager, ActiveState, ip, listeners) that say WHY."
	emit "# AGENT: symptom-indexed catalogue: docs/ci-troubleshooting.md"
	emit "# AGENT: a check that fails on EVERY run and every flavor is a dead gate,"
	emit "#        not a known issue — see the PR quality contract in AGENTS.md."
fi
emit "TUNAOS_INSTALL_CHECKS_RESULT pass=${PASS} fail=${FAIL} desktop=${DESKTOP}"
exit "$FAIL"
