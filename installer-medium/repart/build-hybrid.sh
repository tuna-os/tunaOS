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
losetup -d "${loop}"
python3 "${HERE}/gen-definitions.py" "${defs}/table.json" "${defs}/d"
rm -f "${OUT}"
systemd-repart --empty=create --size=auto --seed=random \
	--definitions="${defs}/d" --el-torito=yes "${OUT}"
rm -rf "${defs}"
echo "hybrid: ${OUT} ready"
