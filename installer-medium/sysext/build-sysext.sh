#!/usr/bin/env bash
# Build the medium-only sysext raw image (tunaOS#4907).
#
# Usage (CI): installer-medium/sysext/build-sysext.sh OUTDIR [--dry-run]
#
# Builds Containerfile.sysext (systemd main at the SYSTEMD_PIN commit plus
# the vendored install toggles patch) and packs /out into OUTDIR as
# medium-sysinstall.raw. With --dry-run, print the commands and exit 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTDIR="${1:?usage: build-sysext.sh OUTDIR [--dry-run]}"
DRY_RUN="${2:-}"
# shellcheck disable=SC1091
source "${HERE}/SYSTEMD_PIN"

echo "sysext: systemd ${REF} + install-toggles -> ${OUTDIR}/medium-sysinstall.raw"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "podman build -f Containerfile.sysext --build-arg SYSTEMD_REF=${REF} (dry run: no image built)"
	echo "mksquashfs /out ${OUTDIR}/medium-sysinstall.raw (dry run)"
	exit 0
fi
# The tag lets repart/build-hybrid.sh run the pinned systemd-repart from this
# image: the runner's own repart (255 on ubuntu-24.04) has no --el-torito.
img="$(podman build -q -t "${MEDIUM_SYSEXT_TAG:-medium-sysext-pack}" -f "${HERE}/Containerfile.sysext" \
	--build-arg "SYSTEMD_REF=${REF}" "${HERE}")"
mkdir -p "${OUTDIR}"
# label=disable: an SELinux host denies the write to the bind mount.
# Each path carries its SELinux label (selinux-pseudo.sh), so the merged /usr
# keeps the labels of the policy. mksquashfs 4.6 reads `PATH x NAME=VALUE`.
podman run --rm --security-opt label=disable -v "${OUTDIR}:/sysext-out" \
	-v "${HERE}/selinux-pseudo.sh:/selinux-pseudo.sh:ro" "${img}" \
	bash -c '/selinux-pseudo.sh /out >/tmp/labels.pseudo &&
		mksquashfs /out /sysext-out/medium-sysinstall.raw -noappend -quiet -pf /tmp/labels.pseudo &&
		unsquashfs -stat /sysext-out/medium-sysinstall.raw | grep -q "Number of xattr ids [1-9]"'
echo "sysext: ${OUTDIR}/medium-sysinstall.raw ready"
