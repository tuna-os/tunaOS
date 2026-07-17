#!/bin/bash
# TAP-style live-image smoke checks for the ISO E2E workflows. Runs INSIDE
# the live guest via SSH (uploaded alongside lib/e2e-assert.sh by
# scripts/iso-e2e.sh's run_install()). Assertions adapted from
# frostyard/snosi's tiered on-VM test scripts (LGPL-2.1-or-later):
# test/tests/01-installation.sh, 02-services.sh and 04-smoke.sh, trimmed to
# what holds on a TunaOS live squash (overlay root, so no read-only-/ or
# composefs assertions) and made distro-aware (rpm/dpkg, sshd/ssh).
#
# The live environment boots the same bootc image that fisherman is about to
# install, so this is cheap pre-install evidence that the image is coherent.
# Output format: TAP-like (ok / not ok), exit code = number of failures.
set -uo pipefail

HELPERS="${TEST_LIB_DIR:-$(dirname "$0")/lib}/e2e-assert.sh"
# shellcheck source=scripts/lib/e2e-assert.sh
source "$HELPERS"

echo "# Live image smoke checks"

# Wait for boot to settle (SSH can be ready before all services finish).
# Accept "degraded" — live squashes routinely carry a few failed units that
# don't affect the install path.
sys_state="starting"
for _ in $(seq 1 60); do
	sys_state=$(systemctl is-system-running 2>/dev/null || true)
	[[ "$sys_state" == "starting" ]] || break
	sleep 2
done
echo "# system state: $sys_state"
check "system has booted (running or degraded)" \
	test "$sys_state" = "running" -o "$sys_state" = "degraded"

check "/usr is read-only" \
	test ! -w /usr/bin

check "bootc status succeeds" \
	sudo bootc status

check "bootc reports an image reference" \
	bash -c 'sudo bootc status --json 2>/dev/null | grep -q "\"image\""'

# shellcheck disable=SC2016
check "machine-id is committed (32-hex)" \
	bash -c '[[ "$(cat /etc/machine-id 2>/dev/null)" =~ ^[0-9a-f]{32}$ ]]'

echo "# Service health"

# Unit name differs across variants: sshd (Fedora/CentOS) vs ssh (Ubuntu).
check "ssh daemon is active" \
	bash -c 'systemctl is-active sshd 2>/dev/null || systemctl is-active ssh'

check "a network manager is active" \
	bash -c 'systemctl is-active NetworkManager 2>/dev/null || systemctl is-active systemd-networkd'

# Informational only: failed units are worth eyeballing but live squashes
# legitimately carry some (e.g. serial-console units on headless boots).
failed_units=$(systemctl --failed --no-legend 2>/dev/null | wc -l)
echo "# failed systemd units: ${failed_units}"
if [[ "$failed_units" -gt 0 ]]; then
	systemctl --failed --no-legend 2>/dev/null | sed 's/^/#   /'
fi

echo "# Smoke"

check "DNS resolution (${SMOKE_DNS_HOST:-ghcr.io})" \
	getent hosts "${SMOKE_DNS_HOST:-ghcr.io}"

check "network connectivity" \
	curl -sf --max-time 10 "${SMOKE_NET_URL:-https://example.com}"

# shellcheck disable=SC2016
check "package metadata intact (>100 installed packages)" \
	bash -c 'if command -v rpm >/dev/null; then n=$(rpm -qa | wc -l); elif command -v dpkg >/dev/null; then n=$(dpkg -l | grep -c "^ii"); elif command -v pacman >/dev/null; then n=$(pacman -Q | wc -l); elif command -v qlist >/dev/null; then n=$(qlist -I | wc -l); else exit 1; fi; test "$n" -gt 100'

# shellcheck disable=SC2016
check "system time is reasonable (year >= 2025)" \
	bash -c 'test "$(date +%Y)" -ge 2025'

# shellcheck disable=SC2016
check "hostname is set" \
	bash -c 'test -n "$(hostname)"'

check "locale is configured" \
	locale

print_summary
