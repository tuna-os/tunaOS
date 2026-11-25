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
# DRY holds the flag as an array so a real run passes no empty argument.
DRY=()
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	MEDIUM_DRY_RUN=1
	DRY=(--dry-run)
fi
export MEDIUM_DRY_RUN

# Run one stage. A dry run still executes each stage, which prints its own
# command and exits 0 (every stage takes --dry-run), so a missing or
# non-executable script fails here instead of in CI.
step() {
	echo "medium: $*"
	[[ -x "$1" ]] || {
		echo "medium: stage script missing or not executable: $1" >&2
		exit 1
	}
	"$@"
}

if [[ "${MEDIUM_DRY_RUN}" = "0" && ${EUID} -ne 0 ]]; then
	echo "medium: run as root (bootc install, loop devices, repart)" >&2
	exit 1
fi

# Work area: the raw disk image and the mount points live here. MEDIUM_WORK
# pins it (CI sets it on a big volume); otherwise a fresh temp dir. A dry run
# only names the paths and creates nothing.
if [[ "${MEDIUM_DRY_RUN}" = "1" ]]; then
	WORK="${MEDIUM_WORK:-${TMPDIR:-/tmp}/medium-work.dry-run}"
else
	WORK="${MEDIUM_WORK:-$(mktemp -d "${TMPDIR:-/tmp}/medium-work.XXXXXX")}"
	mkdir -p "${WORK}"
fi
RAW="${WORK}/medium-raw.img"
MNT="${WORK}/mnt"
MEDIUM_LOOP="" MEDIUM_ROOT="" MEDIUM_ESP=""

# Unmount and detach whatever mount-medium.sh set up. Idempotent: it runs
# before repart (CopyBlocks needs the partitions quiescent) and again on exit.
unmount_medium() {
	[[ -n "${MEDIUM_ESP}" ]] && { umount "${MEDIUM_ESP}" 2>/dev/null || true; }
	[[ -n "${MEDIUM_ROOT}" ]] && { umount "${MEDIUM_ROOT}" 2>/dev/null || true; }
	[[ -n "${MEDIUM_LOOP}" ]] && { losetup -d "${MEDIUM_LOOP}" 2>/dev/null || true; }
	MEDIUM_LOOP="" MEDIUM_ROOT="" MEDIUM_ESP=""
}
cleanup() {
	unmount_medium
	# Only a directory this run created is removed; an explicit MEDIUM_WORK stays.
	if [[ -z "${MEDIUM_WORK:-}" && "${MEDIUM_DRY_RUN}" = "0" ]]; then
		rm -rf -- "${WORK}"
	fi
}
trap cleanup EXIT

# Secure Boot policy (tunaOS#4955). The mode is explicit and has no default:
# CI sets MEDIUM_SECURE_BOOT until the resolver gives each cell a
# `secure_boot` field. It runs after the live entry exists, so the check sees
# every boot binary the medium ships. An unknown mode stops the build.
secure_boot() {
	[[ -n "${MEDIUM_SECURE_BOOT:-}" ]] || return 0
	step "${HERE}/secure-boot/stage-medium.sh" "${MEDIUM_SECURE_BOOT}" "$@"
}

# Order matters. The live layer (step 1) carries everything the live session
# runs: fishermand and its sockets (daemon/build-fishermand.sh), polkit rules,
# and the desktop's frontend with its autostart (frontends/install-frontend.sh).
# It builds into a staging tree inside the image build and copies over /, so
# both land in the root that build-to-disk.sh installs and that repart copies
# at step 5. Nothing writes the mounted medium's /usr: on ostree and composefs
# cells that mount is the sysroot, not the deployment.
step "${HERE}/build-live-image.sh" "${CELL}" "${DRY[@]}"
step "${HERE}/build-to-disk.sh" "${CELL}" "${RAW}" "${DRY[@]}"
EVIDENCE="$(dirname "${OUT}")/medium-evidence"
step "${HERE}/sysext/build-sysext.sh" "${EVIDENCE}" "${DRY[@]}"
if [[ "${MEDIUM_DRY_RUN}" = "0" ]]; then
	# shellcheck disable=SC1090
	source <("${HERE}/mount-medium.sh" "${RAW}" "${MNT}")
	step "${HERE}/add-live-entry.sh" "${CELL}" "${MEDIUM_ROOT}" "${MEDIUM_ESP}"
	secure_boot "${MEDIUM_ROOT}" "${MEDIUM_ESP}"
	step "${HERE}/sysext/place-sysext.sh" "${MEDIUM_ROOT}" "${EVIDENCE}/medium-sysinstall.raw"
	sync
	unmount_medium
else
	step "${HERE}/mount-medium.sh" "${RAW}" "${MNT}" "${DRY[@]}"
	step "${HERE}/add-live-entry.sh" "${CELL}" "${MNT}/root" "${MNT}/efi" "${DRY[@]}"
	secure_boot "${MNT}/root" "${MNT}/efi" "${DRY[@]}"
	step "${HERE}/sysext/place-sysext.sh" "${MNT}/root" "${EVIDENCE}/medium-sysinstall.raw" "${DRY[@]}"
fi
step "${HERE}/repart/build-hybrid.sh" "${CELL}" "${RAW}" "${OUT}" "${DRY[@]}"
step "${HERE}/flatpak/bake-flatpaks.sh" "${CELL}" "${OUT}" "${DRY[@]}"
step "${HERE}/publish/chunk-publish.py" "${CELL}" "${OUT}" "$(dirname "${OUT}")/medium-layout" "${DRY[@]}"
echo "medium: ${OUT} ready"
