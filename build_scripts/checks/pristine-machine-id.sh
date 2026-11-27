#!/usr/bin/env bash
# The image must not carry a machine-id (tunaOS#5103). An apt postinst (dbus)
# commits one while the image builds; every machine installed from it would then
# share that identity, and fishermand refuses such a medium
# ("postfix: medium carries a machine-id ...; it is not pristine", gurnard:pantheon
# run 45993359445). systemd commits a fresh id on the first boot of the
# installed system when the file says `uninitialized`.
#
# Resets the file, then stops the build when it still holds anything else.
# MACHINE_ID_FILE is for the test suite.
set -euo pipefail

file="${MACHINE_ID_FILE:-/etc/machine-id}"
printf 'uninitialized\n' >"${file}"
got="$(<"${file}")"
if [[ "${got}" != uninitialized ]]; then
	echo "ERROR: ${file} holds '${got}'; an image must ship 'uninitialized' (tunaOS#5103)" >&2
	exit 1
fi
