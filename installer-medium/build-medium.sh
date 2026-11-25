#!/usr/bin/env bash
# Build one installer medium image for a variant:flavor cell (tunaOS#4907, #4913).
#
# Usage (CI, root): installer-medium/build-medium.sh CELL OUT.ISO [--dry-run]
#
# The cell is any supported row of scripts/lib/installer_medium.py (the
# resolver over the tunaos.toml matrix and the image evidence). The build runs
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

# Secure Boot policy (tunaOS#4955). The mode, the enroll value and the vendor
# certificate pins come from the cell row of the resolver. MEDIUM_SECURE_BOOT
# replaces the mode for a test or a manual build; an unknown mode stops the
# build. The stage runs after the live entry exists, so it sees every boot
# binary the medium ships.
mapfile -t SB_ROW < <(
	python3 - "${HERE}/.." "${CELL}" <<'PY'
import importlib.util
import sys
from pathlib import Path

root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
row = c.installer_medium_policy().cell(c.load(root / "tunaos.toml"), sys.argv[2])
print(row.get("secure_boot") or "")
print(row.get("secure_boot_enroll") or "")
print(" ".join(row.get("secure_boot_vendor_sha256") or []))
PY
)
[[ ${#SB_ROW[@]} -eq 3 ]] || {
	echo "medium: cannot resolve the Secure Boot fields of ${CELL}" >&2
	exit 1
}
SB_MODE="${MEDIUM_SECURE_BOOT:-${SB_ROW[0]}}"
[[ -z "${SB_ROW[1]}" ]] || export MEDIUM_SB_ENROLL="${MEDIUM_SB_ENROLL:-${SB_ROW[1]}}"
[[ -z "${SB_ROW[2]}" ]] || export MEDIUM_SB_VENDOR_SHA256="${MEDIUM_SB_VENDOR_SHA256:-${SB_ROW[2]}}"
# What the medium carries for Secure Boot, for the publish step: a medium
# with `"staged": false` boots only with Secure Boot off and is not published.
sb_record() {
	[[ "${MEDIUM_DRY_RUN}" = "1" ]] && return 0
	mkdir -p "${EVIDENCE}"
	printf '{"cell": "%s", "mode": "%s", "staged": %s, "reason": "%s"}\n' \
		"${CELL}" "${SB_MODE}" "$1" "$2" >"${EVIDENCE}/secure-boot.json"
}
secure_boot() {
	local root="$1" esp="$2" rc=0
	[[ -n "${SB_MODE}" ]] || return 0
	if [[ "${SB_MODE}" = "tunaos-key" && -z "${MEDIUM_SB_LOADER:-}" ]]; then
		# No signed loader given: CI signs here. Only a trusted event has the
		# key (image-installer.yml); a pull request gets status 3.
		step "${HERE}/secure-boot/sign-medium.sh" "${esp}" "${WORK}/secure-boot" "${DRY[@]}" || rc=$?
		if [[ ${rc} -eq 3 ]]; then
			echo "medium: WARNING: ${CELL} is a tunaos-key cell and this run has no key." >&2
			echo "medium: WARNING: the medium is unsigned; it boots only with Secure Boot off." >&2
			sb_record false "no signing key on this event"
			return 0
		fi
		[[ ${rc} -eq 0 ]] || exit "${rc}"
		export MEDIUM_SB_LOADER="${WORK}/secure-boot/systemd-boot${MEDIUM_SB_ARCH:-x64}.efi.signed"
		export MEDIUM_SB_AUTH_DIR="${WORK}/secure-boot/auth"
	fi
	if [[ "${SB_MODE}" = "tunaos-key" && -z "${MEDIUM_SB_SHIM_DIR:-}" && "${MEDIUM_DRY_RUN}" = "0" ]]; then
		# shim and MokManager by the pin that the signed images use
		# (secure-boot/image/shim.toml). The path inside the image is out of
		# reach: a composefs medium does not show /usr on its mounted root.
		step "${HERE}/secure-boot/image/fetch-shim.sh" "${WORK}/secure-boot/shim"
		export MEDIUM_SB_SHIM_DIR="${WORK}/secure-boot/shim"
	fi
	step "${HERE}/secure-boot/stage-medium.sh" "${SB_MODE}" "${root}" "${esp}" "${DRY[@]}"
	sb_record true "stage-medium.sh ${SB_MODE}"
}

# Order matters. The live layer (step 1) carries everything the live session
# runs: fishermand and its sockets (daemon/build-fishermand.sh), polkit rules,
# and the desktop's frontend with its autostart (frontends/install-frontend.sh).
# It builds into a staging tree inside the image build and copies over /, so
# both land in the root that build-to-disk.sh installs and that repart copies
# at step 5. Nothing writes the mounted medium's /usr: on ostree and composefs
# cells that mount is the sysroot, not the deployment.
step "${HERE}/build-live-image.sh" "${CELL}" "${DRY[@]}"
# The row came from evidence read on one date; the image tag moves nightly.
# Probe the image this run installs and stop on a different layout.
step "${HERE}/verify-cell-layout.sh" "${CELL}" "${DRY[@]}"
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
	secure_boot "${MNT}/root" "${MNT}/efi"
	step "${HERE}/sysext/place-sysext.sh" "${MNT}/root" "${EVIDENCE}/medium-sysinstall.raw" "${DRY[@]}"
fi
step "${HERE}/repart/build-hybrid.sh" "${CELL}" "${RAW}" "${OUT}" "${DRY[@]}"
step "${HERE}/flatpak/bake-flatpaks.sh" "${CELL}" "${OUT}" "${DRY[@]}"
step "${HERE}/publish/chunk-publish.py" "${CELL}" "${OUT}" "$(dirname "${OUT}")/medium-layout" "${DRY[@]}"
echo "medium: ${OUT} ready"
