#!/usr/bin/env bash
# Check that a cell's resolved layout still equals the image it builds from (tunaOS#4905).
#
# Usage: installer-medium/verify-cell-layout.sh CELL [IMAGE] [--dry-run]
#
# The resolver takes bootloader, backend and filesystem from the evidence
# file, which records one image digest on one date. The image tag moves every
# night. This step runs the same probe,
# live-iso/common/src/installer-recipe-backend.sh, inside the image the build
# uses (IMAGE, default the cell's live layer tag) and fails when the answer
# differs from the row, before `bootc install` writes a disk with the wrong
# layout. A declared ext4 in place of a measured btrfs passes. For a cell with
# a declared layout (tromso:kde) the bootloader and backend must match, and a
# filesystem difference is a warning: the probe knows the OS families of the
# matrix only, and no run has shown what it answers on a BuildStream image.
# With --dry-run, print the command and exit 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
CELL="${1:?usage: verify-cell-layout.sh CELL [IMAGE] [--dry-run]}"
IMAGE="${MEDIUM_LIVE_TAG:-medium-live-${CELL%%:*}-${CELL##*:}}"
DRY_RUN=""
for arg in "${@:2}"; do
	if [[ "${arg}" = "--dry-run" ]]; then DRY_RUN="${arg}"; else IMAGE="${arg}"; fi
done
PROBE="${ROOT}/live-iso/common/src/installer-recipe-backend.sh"

mapfile -t want < <(python3 -c 'import importlib.util,sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
row = c.installer_medium_policy().cell(c.load(root / "tunaos.toml"), sys.argv[2])
print({"grub": "grub2", "systemd-boot": "systemd"}[row["bootloader"]])
print("true" if row["backend"] == "composefs" else "false")
print(row["filesystem"])
print(row["source"])' "${ROOT}" "${CELL}")
[[ ${#want[@]} -eq 4 ]] || {
	echo "verify-layout: cannot resolve cell ${CELL}" >&2
	exit 1
}
echo "verify-layout: ${CELL} expects bootloader=${want[0]} composeFsBackend=${want[1]} filesystem=${want[2]}"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "podman run --rm -e TUNAOS_INSTALLER_ALLOW_BTRFS=1 -v ${PROBE}:/run/medium-probe.sh:ro ${IMAGE} bash /run/medium-probe.sh (dry run)"
	exit 0
fi
fail() {
	echo "verify-layout: ${CELL}: $*" >&2
	echo "verify-layout: refresh the evidence with installer-medium/evidence/scan-images.py --cell ${CELL}" >&2
	exit 1
}
# label=disable: on an SELinux host the bind mount of the probe is not
# readable in the container ("bash: /run/medium-probe.sh: Permission denied",
# bihar, 2026-11-25), and a relabel would change the checkout.
got="$(podman run --rm --pull=never --security-opt label=disable -e TUNAOS_INSTALLER_ALLOW_BTRFS=1 \
	-v "${PROBE}:/run/medium-probe.sh:ro" --entrypoint bash "${IMAGE}" /run/medium-probe.sh)" ||
	fail "the probe did not run or could not classify ${IMAGE}"
value() { sed -n "s/^$1=//p" <<<"${got}"; }
[[ "$(value bootloader)" = "${want[0]}" ]] || fail "image bootloader is $(value bootloader), the row says ${want[0]}"
[[ "$(value composeFsBackend)" = "${want[1]}" ]] || fail "image composeFsBackend is $(value composeFsBackend), the row says ${want[1]}"
if [[ "$(value filesystem)" != "${want[2]}" && ! ("$(value filesystem)" = btrfs && "${want[2]}" = ext4) ]]; then
	if [[ "${want[3]}" = declared ]]; then
		echo "verify-layout: WARNING ${CELL}: the probe says filesystem $(value filesystem), the declared row says ${want[2]}" >&2
	else
		fail "image filesystem is $(value filesystem), the row says ${want[2]}"
	fi
fi
echo "verify-layout: ${CELL} matches the image"
