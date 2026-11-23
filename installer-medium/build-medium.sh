#!/usr/bin/env bash
# Build one installer medium image for a variant:flavor cell (tunaOS#4907, #4913).
#
# Usage (CI, root): installer-medium/build-medium.sh CELL OUT.ISO [--dry-run]
#
# The cell comes from [installer_medium.cells] in tunaos.toml. The build runs
# `bootc install to-disk` once from the cell's live layer image, adds the
# medium-only live boot entry, lays out the hybrid El Torito + GPT image with
# systemd-repart, bakes the fixed Flatpak set and the medium-only sysext, and
# publishes the result as a signed installer OCI image. With --dry-run every
# step prints its command and touches nothing; the pytest and bats suites
# drive that mode without root.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CELL="${1:?usage: build-medium.sh CELL OUT.ISO [--dry-run]}"
OUT="${2:?usage: build-medium.sh CELL OUT.ISO [--dry-run]}"
DRY_RUN="${3:-}"
MEDIUM_DRY_RUN=0
[[ "${DRY_RUN}" = "--dry-run" ]] && MEDIUM_DRY_RUN=1
export MEDIUM_DRY_RUN

# The raw disk, mount point and OCI layout all live beside the output image.
# They used to be unbound names, so every stage that took RAW or MNT died
# under `set -u` before it could run. Overridable for harnesses that stage
# their own scratch directories.
WORKDIR="$(dirname "${OUT}")"
RAW="${MEDIUM_RAW:-${WORKDIR}/medium.raw}"
MNT="${MEDIUM_MNT:-${WORKDIR}/medium-mnt}"
LAYOUT="${MEDIUM_LAYOUT:-${WORKDIR}/medium-layout}"

step() {
	echo "medium: $*"
	if [[ "${MEDIUM_DRY_RUN}" = "0" ]]; then
		"$@"
	fi
}

if [[ "${MEDIUM_DRY_RUN}" = "0" && ${EUID} -ne 0 ]]; then
	echo "medium: run as root (bootc install, loop devices, repart)" >&2
	exit 1
fi
step "${HERE}/build-live-image.sh" "${CELL}" "${DRY_RUN}"
step "${HERE}/build-to-disk.sh" "${CELL}" "${RAW}" "${DRY_RUN}"
EVIDENCE="$(dirname "${OUT}")/medium-evidence"
step "${HERE}/sysext/build-sysext.sh" "${EVIDENCE}" "${DRY_RUN}"
if [[ "${MEDIUM_DRY_RUN}" = "0" ]]; then
	# shellcheck disable=SC1090
	source <("${HERE}/mount-medium.sh" "${RAW}" "${MNT}" "${DRY_RUN}")
	step "${HERE}/add-live-entry.sh" "${CELL}" "${MEDIUM_ROOT}" "${MEDIUM_ESP}"
	step "${HERE}/sysext/place-sysext.sh" "${MEDIUM_ROOT}" "${EVIDENCE}/medium-sysinstall.raw"
else
	echo "medium: mount-medium.sh ${RAW} ${MNT} (dry run)"
	echo "medium: add-live-entry.sh ${CELL} <root> <esp> (dry run)"
	echo "medium: sysext/place-sysext.sh <root> <sysext> (dry run)"
fi
step "${HERE}/repart/build-hybrid.sh" "${CELL}" "${RAW}" "${OUT}" "${DRY_RUN}"
step "${HERE}/flatpak/bake-flatpaks.sh" "${CELL}" "${OUT}" "${DRY_RUN}"
step python3 "${HERE}/publish/chunk-publish.py" "${CELL}" "${OUT}" "${LAYOUT}" "${DRY_RUN}"
echo "medium: ${OUT} ready"
