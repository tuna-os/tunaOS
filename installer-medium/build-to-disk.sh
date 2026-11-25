#!/usr/bin/env bash
# Install a cell's published digest to a blank disk image (tunaOS#4907).
#
# Usage (CI, root): installer-medium/build-to-disk.sh CELL OUT.RAW [--dry-run]
#
# CELL is variant:flavor from [installer_medium.cells]. The image ref is the
# cell's published ref, resolved by scripts/published-image-ref.sh; the
# backend and bootloader come from the cell row (ostree + grub on EL10,
# composefs + systemd-boot on tromso:kde), mirroring Utah's build-raw-image.sh
# and Dakota's image-installer/build-raw-image.sh. With --dry-run, print the
# bootc command and exit 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
CELL="${1:?usage: build-to-disk.sh CELL OUT.RAW [--dry-run]}"
OUT="${2:?usage: build-to-disk.sh CELL OUT.RAW [--dry-run]}"
DRY_RUN="${3:-}"

row() {
	python3 -c 'import importlib.util,sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
medium = c.installer_medium_policy()
cell = medium.cell(c.load(root / "tunaos.toml"), sys.argv[2])
print(cell[sys.argv[3]])' "${ROOT}" "${CELL}" "$1"
}
FILESYSTEM="$(row filesystem)"
BOOTLOADER="$(row bootloader)"
BACKEND="$(row backend)"
TAG="medium-live-${CELL%%:*}-${CELL##*:}"
LIVE_IMAGE="${MEDIUM_LIVE_TAG:-${TAG}}"
SOURCE_IMAGE="$("${HERE}/resolve-cell-image.sh" "${CELL}")"
INSTALL_IMAGE="$([ "${MEDIUM_USE_CELL_REF:-0}" = "1" ] && echo "${SOURCE_IMAGE}" || echo "${LIVE_IMAGE}")"
args=(--generic-image --target-imgref "${SOURCE_IMAGE}")
if [[ "${FILESYSTEM}" != "xfs" ]]; then
	args+=(--filesystem "${FILESYSTEM}")
fi
if [[ "${BACKEND}" = "composefs" ]]; then
	args+=(--composefs-backend)
fi
if [[ "${BOOTLOADER}" = "systemd-boot" ]]; then
	args+=(--bootloader systemd)
fi
# rhgb quiet: the graphical, branded Plymouth splash and LUKS prompt on the
# installed disk (measured on Utah's medium; fisherman adds splash in-repo).
args+=(--karg rhgb --karg quiet)

# The disk is sized from the image, not fixed: xfs cannot shrink, and the
# hybrid copies the root partition whole (tunaOS#4974). MEDIUM_RAW_SIZE
# overrides. Otherwise: image size x1.25 (filesystem and ostree overhead)
# + MEDIUM_FLATPAK_RESERVE_MB for the deployed Flatpak set (baked after this
# step) + MEDIUM_BOOT_RESERVE_MB for the ESP, boot and BIOS partitions.
medium_size() {
	if [[ -n "${MEDIUM_RAW_SIZE:-}" ]]; then
		echo "${MEDIUM_RAW_SIZE}"
		return
	fi
	local bytes
	bytes="$(podman image inspect --format '{{.Size}}' "${INSTALL_IMAGE}" 2>/dev/null || true)"
	[[ "${bytes}" =~ ^[0-9]+$ ]] || {
		echo "build-to-disk: cannot read the size of ${INSTALL_IMAGE}; set MEDIUM_RAW_SIZE" >&2
		return 1
	}
	echo "$(((bytes / 1048576) * 5 / 4 + ${MEDIUM_FLATPAK_RESERVE_MB:-4096} + ${MEDIUM_BOOT_RESERVE_MB:-2048}))M"
}

echo "bootc install to-disk ${INSTALL_IMAGE} -> ${OUT} (${MEDIUM_RAW_SIZE:-sized from the image}, ${FILESYSTEM}/${BOOTLOADER}/${BACKEND})"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	printf 'bootc install to-disk'
	printf ' %q' "${args[@]}" "${INSTALL_IMAGE}" "${OUT}"
	printf ' %s\n' "(dry run: no image written)"
	exit 0
fi
[[ ${EUID} -eq 0 ]] || {
	echo "build-to-disk: run as root (bootc install, loop devices)" >&2
	exit 1
}
rm -f "${OUT}"
SIZE="$(medium_size)"
echo "build-to-disk: disk size ${SIZE}"
truncate -s "${SIZE}" "${OUT}"
data="$(dirname "${OUT}")"
# The install runs inside the image, as on Utah's and Dakota's spikes: the
# image's own mkfs and bootc see the loop device directly.
podman run --rm --privileged --pid=host -v /dev:/dev -v "${data}:/data" \
	"${INSTALL_IMAGE}" bootc install to-disk "${args[@]}" --via-loopback "/data/$(basename "${OUT}")"
