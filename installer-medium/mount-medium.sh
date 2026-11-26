#!/usr/bin/env bash
# Loop-mount a medium raw image for surgery (tunaOS#4907).
#
# Usage: eval "$(installer-medium/mount-medium.sh RAW MNT [--dry-run])"
#
# Prints export lines for MEDIUM_LOOP, MEDIUM_ROOT and MEDIUM_ESP. The caller
# unmounts and detaches on exit (the orchestrator owns the trap). With
# --dry-run, print the commands that would run and exit 0.
set -euo pipefail

RAW="${1:?usage: mount-medium.sh RAW MNT [--dry-run]}"
MNT="${2:?usage: mount-medium.sh RAW MNT [--dry-run]}"
DRY_RUN="${3:-}"

if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "losetup --find --show --partscan ${RAW}"
	echo "mount <root-part> ${MNT}/root; mount <esp-part> ${MNT}/efi"
	echo "export MEDIUM_LOOP=<loop> MEDIUM_ROOT=${MNT}/root MEDIUM_ESP=${MNT}/efi"
	exit 0
fi
[[ ${EUID} -eq 0 ]] || {
	echo "mount-medium: run as root (loop devices)" >&2
	exit 1
}

loop="$(losetup --find --show --partscan "${RAW}")"
udevadm settle
mkdir -p "${MNT}/root" "${MNT}/efi"
esp="" root="" boot=""
for p in "${loop}"p*; do
	ptype="$(blkid -p -s PART_ENTRY_TYPE -o value "$p" | tr '[:upper:]' '[:lower:]')"
	fstype="$(blkid -p -s TYPE -o value "$p" || true)"
	if [[ "${ptype}" == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" ]]; then
		esp="$p"
	elif [[ "${ptype}" == "bc13c2ff-59e6-4262-a352-b275fd6f7172" ]]; then
		boot="$p"
	elif [[ -n "${fstype}" ]]; then
		root="$p"
	fi
done
[[ -n "${esp}" && -n "${root}" ]] || {
	echo "mount-medium: no ESP+root on ${RAW}" >&2
	exit 1
}
mount "${root}" "${MNT}/root"
# A GRUB cell keeps /boot on its own partition (build-to-disk.sh).
[[ -z "${boot}" ]] || mount "${boot}" "${MNT}/root/boot"
mount "${esp}" "${MNT}/efi"
echo "export MEDIUM_LOOP=${loop} MEDIUM_ROOT=${MNT}/root MEDIUM_ESP=${MNT}/efi"
