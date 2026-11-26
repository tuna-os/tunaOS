#!/usr/bin/env bash
# Bake the fixed Flatpak set into the medium's /var (tunaOS#4907).
#
# Usage: installer-medium/flatpak/bake-flatpaks.sh CELL TARGET [--dry-run]
#
# TARGET is the mounted medium root, or a disk image to loop-mount (CI).
# Installs exactly the [flatpak_preinstall] table from tunaos.toml for the
# cell's desktop (common plus its desktop_additions) into the medium's
# /var/lib/flatpak, then runs scripts/check-flatpak-medium.py so the baked
# set and the generated policy can never drift. With --dry-run, print the
# install list and exit 0.
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

echo "flatpak: bake $(apps | wc -l) apps for ${DESKTOP} into the /var/lib/flatpak of ${TARGET}"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	apps | sed 's/^/flatpak install --system --no-deploy --no-related /'
	echo "check-flatpak-medium.py --desktop ${DESKTOP} --preinstall-dir <root>/usr/share/flatpak/preinstall.d (dry run)"
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
	# The ESP and the /boot of a GRUB cell come first: the root is the partition
	# that is neither.
	root_part="$(for p in "${loop}"p*; do
		ptype="$(blkid -p -s PART_ENTRY_TYPE -o value "$p" | tr '[:upper:]' '[:lower:]')"
		case "${ptype}" in
		c12a7328-f81f-11d2-ba4b-00a0c93ec93b | bc13c2ff-59e6-4262-a352-b275fd6f7172) continue ;;
		esac
		fstype="$(blkid -p -s TYPE -o value "$p" || true)"
		[[ -n "${fstype}" ]] && echo "$p" && break
	done)"
	mount "${root_part}" "${mnt}"
	# shellcheck disable=SC2064
	trap "umount ${mnt}; losetup -d ${loop}; rm -rf ${mnt}" EXIT
fi
# The system installation of the medium, not of the build host. flatpak has
# no --target-dir option; FLATPAK_SYSTEM_DIR names the installation. On an
# ostree or composefs medium the mounted root is the sysroot, so /var is the
# var directory of the deployment (medium-paths.sh).
# shellcheck disable=SC1091
source "${HERE}/../medium-paths.sh"
var_lib="$(medium_var_dir "${mnt}")/lib/flatpak"
mkdir -p "${var_lib}"
export FLATPAK_SYSTEM_DIR="${var_lib}"
REMOTE="${MEDIUM_FLATPAK_REMOTE:-flathub}"
REMOTE_URL="${MEDIUM_FLATPAK_REMOTE_URL:-https://dl.flathub.org/repo/flathub.flatpakrepo}"
flatpak remote-add --system --if-not-exists "${REMOTE}" "${REMOTE_URL}"
while read -r id branch; do
	[[ -n "${id}" ]] || continue
	flatpak install --system --noninteractive --no-deploy --no-related \
		"${REMOTE}" "${id}"//"${branch}"
done < <(apps)
check_args=()
while read -r id branch; do
	[[ -n "${id}" ]] || continue
	check_args+=(--app "${id}//${branch}")
done < <(apps)
python3 "${ROOT}/scripts/check-flatpak-medium.py" --desktop "${DESKTOP}" "${check_args[@]}"
echo "flatpak: baked"
