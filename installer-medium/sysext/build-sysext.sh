#!/usr/bin/env bash
# Build the medium-only sysext raw image (tunaOS#4907).
#
# Usage (CI): installer-medium/sysext/build-sysext.sh OUTDIR [--dry-run]
#
# Builds Containerfile.sysext (systemd main at the SYSTEMD_PIN commit plus
# the vendored install toggles patch) and packs /out into OUTDIR as
# medium-sysinstall.raw. With --dry-run, print the commands and exit 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTDIR="${1:?usage: build-sysext.sh OUTDIR [--dry-run]}"
DRY_RUN="${2:-}"
# shellcheck disable=SC1091
source "${HERE}/SYSTEMD_PIN"

echo "sysext: systemd ${REF} + install-toggles -> ${OUTDIR}/medium-sysinstall.raw"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "podman build -f Containerfile.sysext --build-arg SYSTEMD_REF=${REF} (dry run: no image built)"
	echo "mksquashfs /out ${OUTDIR}/medium-sysinstall.raw (dry run)"
	exit 0
fi
img="$(podman build -q -f "${HERE}/Containerfile.sysext" \
	--build-arg "SYSTEMD_REF=${REF}" "${HERE}")"
mkdir -p "${OUTDIR}"
podman run --rm -v "${OUTDIR}:/sysext-out" "${img}" \
	mksquashfs /out /sysext-out/medium-sysinstall.raw -noappend -quiet
echo "sysext: ${OUTDIR}/medium-sysinstall.raw ready"
