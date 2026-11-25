#!/usr/bin/env bash
# Lay out the hybrid medium: one image that boots as CD and as dd'd USB (tunaOS#4913).
#
# Usage (CI, root): installer-medium/repart/build-hybrid.sh CELL RAW OUT.ISO [--dry-run]
#
# Builds the final image with `systemd-repart --el-torito=yes`, as GNOME OS
# does (gnome-build-meta elements/gnomeos/live-image.bst): the ESP becomes the
# El Torito boot image for CD boots, and a GPT stays in place for USB boots.
# Every partition block-copies the raw image's partitions (CopyBlocks= by
# PARTUUID, written by gen-definitions.py), so the medium is byte-for-byte the
# image the installer copies or migrates from. With --dry-run, print the
# repart command and exit 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
CELL="${1:?usage: build-hybrid.sh CELL RAW OUT.ISO [--dry-run]}"
RAW="${2:?usage: build-hybrid.sh CELL RAW OUT.ISO [--dry-run]}"
OUT="${3:?usage: build-hybrid.sh CELL RAW OUT.ISO [--dry-run]}"
DRY_RUN="${4:-}"
BOOTLOADER="$(python3 -c 'import importlib.util,sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
print(c.installer_medium_policy().cell(c.load(root / "tunaos.toml"), sys.argv[2])["bootloader"])' \
	"${ROOT}" "${CELL}")"
# The ESP must already hold the live payload add-live-entry.sh copied onto
# it: repart copies the partitions as they are. A CD boot reads the live
# kernel and initrd off the ESP because it cannot see /boot. The NVIDIA
# initrd alone is about 224 MB (Dakota spike); if the live payload does not
# fit, add-live-entry.sh fails before this step runs.

echo "systemd-repart --el-torito=yes ${RAW} -> ${OUT} (${BOOTLOADER} cell)"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "sfdisk --json ${RAW} | gen-definitions.py <defs>"
	echo "systemd-repart --empty=create --size=auto --seed=random --definitions=<defs> --el-torito=yes ${OUT} (dry run: no image written)"
	exit 0
fi
[[ ${EUID} -eq 0 ]] || {
	echo "build-hybrid: run as root (loop devices, repart)" >&2
	exit 1
}
defs="$(mktemp -d)"
loop="$(losetup --find --show --partscan "${RAW}")"
udevadm settle
sfdisk --json "${loop}" >"${defs}/table.json"
# The loop device stays attached until repart ends: CopyBlocks= names
# /dev/disk/by-partuuid/..., and those links exist only while it is attached.
trap 'losetup -d "${loop}" 2>/dev/null || true' EXIT
python3 "${HERE}/gen-definitions.py" "${defs}/table.json" "${defs}/d"
rm -f "${OUT}"
# --el-torito came with systemd 261. ubuntu-24.04 has 255.4, which stops with
# "systemd-repart: unrecognized option '--el-torito=yes'" (measured in the
# runner image, 2026-11-25). The sysext image holds the pinned repart of
# sysext/Containerfile.sysext, so run that one when the host tool is too old.
# CopyBlocks= reads the partitions of RAW through /dev, hence --privileged.
# The log target is the console: in a container systemd tools log to the
# kernel log of the host, and a failed run printed nothing (run 45554457740).
if systemd-repart --help 2>/dev/null | grep -q -- '--el-torito'; then
	systemd-repart --empty=create --size=auto --seed=random \
		--definitions="${defs}/d" --el-torito=yes "${OUT}"
else
	tools="${MEDIUM_SYSEXT_TAG:-medium-sysext-pack}"
	podman image exists "${tools}" || {
		echo "build-hybrid: host systemd-repart has no --el-torito and image ${tools} is absent (run sysext/build-sysext.sh first)" >&2
		exit 1
	}
	out_dir="$(cd "$(dirname "${OUT}")" && pwd)"
	raw_dir="$(cd "$(dirname "${RAW}")" && pwd)"
	podman run --rm --privileged --pull=never -v /dev:/dev \
		-v "${defs}/d:/defs:ro" -v "${out_dir}:/out-dir" -v "${raw_dir}:${raw_dir}" \
		-e LD_LIBRARY_PATH=/out/usr/lib64/medium-sysinstall \
		-e SYSTEMD_LOG_TARGET=console -e SYSTEMD_LOG_LEVEL=info "${tools}" \
		/out/usr/libexec/medium-sysinstall/systemd-repart --empty=create --size=auto --seed=random \
		--definitions=/defs --el-torito=yes "/out-dir/$(basename "${OUT}")"
fi
losetup -d "${loop}"
trap - EXIT
rm -rf "${defs}"
echo "hybrid: ${OUT} ready"
