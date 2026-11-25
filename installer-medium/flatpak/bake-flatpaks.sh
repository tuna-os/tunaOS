#!/usr/bin/env bash
# Bake the fixed Flatpak set into the medium's /var (tunaOS#4907).
#
# Usage: installer-medium/flatpak/bake-flatpaks.sh CELL TARGET [--dry-run]
#
# TARGET is the mounted medium root, or a disk image to loop-mount (CI).
# Installs and DEPLOYS exactly the [flatpak_preinstall] table from tunaos.toml
# for the cell's desktop (common plus its desktop_additions) into the medium's
# /var/lib/flatpak, so the apps run in the live session and on the installed
# system without a first-boot step. Then runs scripts/check-flatpak-medium.py
# against the store itself (flatpak list), not the list this script read, so
# the baked set and the generated policy can never drift. With --dry-run,
# print the install list and exit 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
CELL="${1:?usage: bake-flatpaks.sh CELL TARGET [--dry-run]}"
TARGET="${2:?usage: bake-flatpaks.sh CELL TARGET [--dry-run]}"
DRY_RUN="${3:-}"
# The desktop is the flavor up to its first dash (kde-nvidia bakes the kde
# set), as scripts/lib/installer_medium.py resolves it.
DESKTOP="$(python3 -c 'import importlib.util,sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
print(c.installer_medium_policy().cell(c.load(root / "tunaos.toml"), sys.argv[2])["desktop"])' "${ROOT}" "${CELL}")"

apps() {
	python3 -c 'import importlib.util,sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
for app in c.flatpak_policy().apps(c.load(root / "tunaos.toml"), sys.argv[2]):
    print(app["id"] + " " + app["branch"])' "${ROOT}" "${DESKTOP}"
}

echo "flatpak: bake $(apps | wc -l) apps for ${DESKTOP} into ${TARGET}:/var/lib/flatpak"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	apps | sed 's/^/flatpak install --system --noninteractive --no-related /'
	echo "check-flatpak-medium.py --desktop ${DESKTOP} --store <root>/var/lib/flatpak (dry run)"
	exit 0
fi
[[ ${EUID} -eq 0 ]] || {
	echo "bake-flatpaks: run as root (loop devices)" >&2
	exit 1
}
mnt="${TARGET}"
if [[ ! -d "${TARGET}" ]]; then
	mnt="$(mktemp -d)"
	loop="$(losetup --find --show --partscan "${TARGET}")"
	udevadm settle
	root_part="$(for p in "${loop}"p*; do
		fstype="$(blkid -p -s TYPE -o value "$p" || true)"
		[[ -n "${fstype}" && "${fstype}" != vfat ]] && echo "$p" && break
	done)"
	mount "${root_part}" "${mnt}"
	# shellcheck disable=SC2064
	trap "umount ${mnt}; losetup -d ${loop}; rm -rf ${mnt}" EXIT
fi
var_lib="${mnt}/var/lib/flatpak"
mkdir -p "${var_lib}"
# FLATPAK_SYSTEM_DIR points the system installation at the medium's store;
# the remotes are read from /etc/flatpak/remotes.d of the build host.
export FLATPAK_SYSTEM_DIR="${var_lib}"
while read -r id branch; do
	[[ -n "${id}" ]] || continue
	flatpak install --system --noninteractive --no-related "${id}"//"${branch}"
done < <(apps)
python3 "${ROOT}/scripts/check-flatpak-medium.py" --desktop "${DESKTOP}" --store "${var_lib}"
echo "flatpak: baked"
