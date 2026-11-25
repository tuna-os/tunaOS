#!/usr/bin/env bash
# Apply the Secure Boot mode of a cell to a mounted medium (tunaOS#4955).
#
# Usage (CI): installer-medium/secure-boot/stage-medium.sh MODE ROOT ESP [--dry-run]
#
# MODE is `distro-chain` or `tunaos-key`; anything else stops the build.
#   distro-chain  verifies shim, the loader and every kernel against the
#                 certificate inside shim. Stages nothing.
#                   MEDIUM_SB_VENDOR_SHA256  sha256 pins for that certificate,
#                                            space-separated (from the cell row)
#   tunaos-key    verifies, then stages shim, MokManager, the certificate and
#                 the key bundle. Inputs (CI sets them; the defaults name the
#                 image contract in docs/SECURE-BOOT.md):
#                   MEDIUM_SB_SHIM_DIR  shim and MokManager (Microsoft-signed)
#                   MEDIUM_SB_LOADER    systemd-boot signed by ci-sign.sh
#                   MEDIUM_SB_AUTH_DIR  PK.auth, KEK.auth, db.auth from ci-sign.sh
#                   MEDIUM_SB_ENROLL    if-safe (default), manual, off, force
#                   MEDIUM_SB_ARCH      x64 (default) or aa64
# With --dry-run, print the layout and touch nothing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USAGE="usage: stage-medium.sh MODE ROOT ESP [--dry-run]"
MODE="${1:?${USAGE}}"
ROOT="${2:?${USAGE}}"
ESP="${3:?${USAGE}}"
DRY_RUN="${4:-}"
ARCH="${MEDIUM_SB_ARCH:-x64}"
TOOL=(python3 "${HERE}/secureboot.py")

case "${MODE}" in
distro-chain | tunaos-key) ;;
*)
	echo "secure-boot: unknown mode '${MODE}' (distro-chain or tunaos-key)" >&2
	exit 1
	;;
esac

if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	exec "${TOOL[@]}" plan "${MODE}" --arch "${ARCH}"
fi

if [[ "${MODE}" = "distro-chain" ]]; then
	BOOT=()
	[[ -d "${ROOT}/boot/loader/entries" ]] && BOOT=(--boot "${ROOT}/boot")
	PINS=()
	for pin in ${MEDIUM_SB_VENDOR_SHA256:-}; do
		PINS+=(--pin-sha256 "${pin}")
	done
	exec "${TOOL[@]}" check --esp "${ESP}" "${BOOT[@]}" --arch "${ARCH}" "${PINS[@]}"
fi

SHARE="${ROOT}/usr/lib/tunaos/secure-boot"
ENROLL="${MEDIUM_SB_ENROLL:-if-safe}"
FORCE=()
[[ "${ENROLL}" = "force" ]] && FORCE=(--allow-force)
exec "${TOOL[@]}" stage --esp "${ESP}" --arch "${ARCH}" --enroll "${ENROLL}" "${FORCE[@]}" \
	--shim-dir "${MEDIUM_SB_SHIM_DIR:-${SHARE}}" \
	--loader "${MEDIUM_SB_LOADER:-${ROOT}/usr/lib/systemd/boot/efi/systemd-boot${ARCH}.efi.signed}" \
	--auth-dir "${MEDIUM_SB_AUTH_DIR:-${SHARE}/keys/auto}"
