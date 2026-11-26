#!/usr/bin/env bash
# Place the medium-only sysext on the mounted medium (tunaOS#4907).
#
# Usage: installer-medium/sysext/place-sysext.sh ROOT SYSEXT.RAW [--dry-run]
#
# Installs the sysext built by build-sysext.sh into the medium's
# /var/lib/extensions, where systemd-sysext merges it on live boots only.
# The install post-hook (installer-medium/hooks/) removes it from the
# installed copy. With --dry-run, print the install and exit 0.
set -euo pipefail

ROOT="${1:?usage: place-sysext.sh ROOT SYSEXT.RAW [--dry-run]}"
SYSEXT="${2:?usage: place-sysext.sh ROOT SYSEXT.RAW [--dry-run]}"
DRY_RUN="${3:-}"

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../medium-paths.sh"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "sysext: ${SYSEXT} -> <var of the deployment under ${ROOT}>/lib/extensions/medium-sysinstall.raw"
	echo "(dry run: nothing installed)"
	exit 0
fi
# ROOT is the sysroot on an ostree or composefs medium; the system reads
# /var/lib/extensions from the var directory of its deployment.
VAR="$(medium_var_dir "${ROOT}")"
echo "sysext: ${SYSEXT} -> ${VAR}/lib/extensions/medium-sysinstall.raw"
install -D -m 0644 "${SYSEXT}" "${VAR}/lib/extensions/medium-sysinstall.raw"
echo "sysext: placed"
