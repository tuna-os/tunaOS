#!/bin/bash
# TAP-style LUKS/TPM evidence checks for the LUKS E2E workflow. Runs INSIDE
# the just-installed guest via SSH (uploaded alongside lib/e2e-assert.sh by
# scripts/iso-e2e.sh's run_install()). Pattern borrowed from frostyard/snosi's
# test/tests/01-installation.sh tiered-check style.
set -uo pipefail

HELPERS="${TEST_LIB_DIR:-$(dirname "$0")}/e2e-assert.sh"
# shellcheck source=scripts/lib/e2e-assert.sh
# A missing helper leaves check() undefined, and every assertion then
# prints nothing while bash writes command-not-found to stderr. Bail out
# loudly instead -- see the note in e2e-installer-gui-checks.sh, where
# exactly that went unnoticed across every smoke run.
if [[ ! -r "$HELPERS" ]]; then
	echo "Bail out! cannot read assertion helpers at ${HELPERS}"
	exit 99
fi
source "$HELPERS"

echo "# LUKS/TPM install evidence"

luks_part=$(sudo lsblk -prno NAME,FSTYPE /dev/vda | awk '$2=="crypto_LUKS"{print $1;exit}')

check "installed disk has a crypto_LUKS partition" \
	test -n "$luks_part"

if [[ -n "$luks_part" ]]; then
	check "LUKS header has a systemd-tpm2 enrollment token" \
		bash -c "sudo cryptsetup luksDump '$luks_part' | grep -qi systemd-tpm2"
else
	echo "not ok - LUKS header has a systemd-tpm2 enrollment token"
	echo "# skipped: no crypto_LUKS partition found to dump"
	FAIL=$((FAIL + 1))
fi

print_summary
