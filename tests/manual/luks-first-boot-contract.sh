#!/usr/bin/env bash
# Drive luks-first-boot.py against a fake QEMU serial and assert it classifies
# the desktop contract as ok / fail / absent.
#
# NOT in the bats suite: luks-first-boot.py waits 60s past login for the TPM
# enrollment window, so this takes ~4 minutes. Run it by hand when changing
# the contract detection.
#
#   ./tests/manual/luks-first-boot-contract.sh
#
# Sockets go in /tmp, not the repo or a scratch dir: AF_UNIX paths are capped
# at ~108 bytes and a deep temp path silently fails to bind.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1
rc=0
for mode in ok fail absent; do
	d=$(mktemp -d /tmp/lfb.XXXX)
	python3 tests/manual/fake-qemu-serial.py "$d" "$mode" &
	fs=$!
	sleep 1
	out=$(timeout 200 python3 scripts/luks-first-boot.py "$d/ser.sock" "$d/mon.sock" testpass 180 20 2>&1)
	kill $fs 2>/dev/null
	rm -rf "$d"
	got=$(grep -o 'LUKS_FIRST_BOOT_DESKTOP_CONTRACT=[a-z]*' <<<"$out" | cut -d= -f2)
	if [[ "$got" == "$mode" ]]; then
		echo "ok - $mode"
	else
		echo "not ok - $mode (got '${got:-<none>}')"
		rc=1
	fi
done
exit $rc
