#!/usr/bin/env bash
# Install a cell's published digest to a blank disk image (tunaOS#4907).
#
# Usage (CI, root): installer-medium/build-to-disk.sh CELL OUT.RAW [--dry-run]
#
# CELL is variant:flavor from [installer_medium.cells]. The image ref is the
# cell's published ref, resolved by scripts/published-image-ref.sh; the
# backend and bootloader come from the cell row (ostree + grub on EL10,
# composefs + systemd-boot on tromso:kde), mirroring Utah's build-raw-image.sh
# and Dakota's image-installer/build-raw-image.sh. A GRUB cell gets a separate
# /boot. With --dry-run, print the bootc command and exit 0.
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

# GRUB reads its configuration, the kernel and the initrd from /boot. The
# install encrypts the root, so /boot of a GRUB cell is a partition of its own:
# GRUB cannot open a LUKS2 volume that the TPM unlocks. `bootc install to-disk`
# writes a /boot partition only with --block-setup tpm2-luks, and the medium is
# plain, so these cells get their partitions here and `bootc install
# to-filesystem`. A systemd-boot cell keeps its kernels on the ESP: to-disk.
ESP_TYPE=c12a7328-f81f-11d2-ba4b-00a0c93ec93b
BOOT_TYPE=bc13c2ff-59e6-4262-a352-b275fd6f7172
BIOS_TYPE=21686148-6449-6e6f-744e-656564454649
ROOT_TYPE=4f68bce3-e8cd-4db1-96e7-fbcaf984b709
BOOT_MIB="${MEDIUM_BOOT_MIB:-2048}"

# The disk is sized from the image, not fixed: xfs cannot shrink, and the
# hybrid copies the root partition whole (tunaOS#4974). MEDIUM_RAW_SIZE
# overrides. Otherwise: image size x1.25 (filesystem and ostree overhead)
# + MEDIUM_FLATPAK_RESERVE_MB for the deployed Flatpak set (baked after this
# step) + MEDIUM_BOOT_RESERVE_MB for the ESP, boot and BIOS partitions
# (default: the /boot partition of a GRUB cell + 1 GiB).
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
	echo "$(((bytes / 1048576) * 5 / 4 + ${MEDIUM_FLATPAK_RESERVE_MB:-4096} + ${MEDIUM_BOOT_RESERVE_MB:-$((BOOT_MIB + 1024))}))M"
}

echo "bootc install ${INSTALL_IMAGE} -> ${OUT} (${MEDIUM_RAW_SIZE:-sized from the image}, ${FILESYSTEM}/${BOOTLOADER}/${BACKEND})"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	if [[ "${BOOTLOADER}" = "grub" ]]; then
		echo "sfdisk ${OUT}: BIOS boot 1 MiB, ESP 512 MiB, /boot ${BOOT_MIB} MiB (ext4), root (${FILESYSTEM})"
		printf 'bootc install to-filesystem'
		printf ' %q' "${args[@]}" --boot-mount-spec UUID=BOOT --root-mount-spec UUID=ROOT "${INSTALL_IMAGE}" "${OUT}"
	else
		printf 'bootc install to-disk'
		printf ' %q' "${args[@]}" "${INSTALL_IMAGE}" "${OUT}"
	fi
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
if [[ "${BOOTLOADER}" != "grub" ]]; then
	podman run --rm --privileged --pid=host -v /dev:/dev -v "${data}:/data" \
		"${INSTALL_IMAGE}" bootc install to-disk "${args[@]}" --via-loopback "/data/$(basename "${OUT}")"
	exit 0
fi

# The BIOS boot partition is there for bootupd: --generic-image installs each
# bootloader of the image. gen-definitions.py leaves it out of the medium.
sfdisk --label gpt "${OUT}" <<EOF
size=1MiB, type=${BIOS_TYPE}, name="BIOS-BOOT"
size=512MiB, type=${ESP_TYPE}, name="EFI-SYSTEM"
size=${BOOT_MIB}MiB, type=${BOOT_TYPE}, name="boot"
type=${ROOT_TYPE}, name="root"
EOF
loop="$(losetup --find --show --partscan "${OUT}")"
target="$(mktemp -d)"
detach() {
	umount -R "${target}" 2>/dev/null || true
	losetup -d "${loop}" 2>/dev/null || true
	rmdir "${target}" 2>/dev/null || true
}
trap detach EXIT
udevadm settle
podman run --rm --privileged -v /dev:/dev --entrypoint bash "${INSTALL_IMAGE}" -euxc '
	mkfs.vfat -F 32 -n EFI-SYSTEM "$1p2"
	mkfs.ext4 -q -F -L boot "$1p3"
	case "$2" in
	xfs) mkfs.xfs -q -f -L root "$1p4" ;;
	btrfs) mkfs.btrfs -q -f -L root "$1p4" ;;
	ext4) mkfs.ext4 -q -F -L root "$1p4" ;;
	*) exit 1 ;;
	esac' -- "${loop}" "${FILESYSTEM}"
udevadm settle
mount "${loop}p4" "${target}"
mkdir "${target}/boot"
mount "${loop}p3" "${target}/boot"
mkdir "${target}/boot/efi"
mount "${loop}p2" "${target}/boot/efi"
fs_args=()
skip=0
for arg in "${args[@]}"; do
	# --filesystem is a to-disk option: the root exists already.
	if ((skip)); then
		skip=0
		continue
	fi
	if [[ "${arg}" = "--filesystem" ]]; then
		skip=1
		continue
	fi
	fs_args+=("${arg}")
done
podman run --rm --privileged --pid=host --security-opt label=disable -v /dev:/dev -v "${target}:/target" \
	"${INSTALL_IMAGE}" bootc install to-filesystem "${fs_args[@]}" \
	--boot-mount-spec "UUID=$(blkid -p -s UUID -o value "${loop}p3")" \
	--root-mount-spec "UUID=$(blkid -p -s UUID -o value "${loop}p4")" \
	--acknowledge-destructive /target
sync
detach
trap - EXIT
