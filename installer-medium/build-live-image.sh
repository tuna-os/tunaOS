#!/usr/bin/env bash
# Build the medium's live layer image (tunaOS#4907).
#
# Usage: installer-medium/build-live-image.sh CELL [--dry-run]
#
# CI builds Containerfile.live FROM the cell's published ref (never a moving
# tag: resolve-cell-image.sh prints the ref CI pinned) and tags it for the
# to-disk step. With --dry-run, print the podman command and exit 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CELL="${1:?usage: build-live-image.sh CELL [--dry-run]}"
DRY_RUN="${2:-}"
TAG="medium-live-${CELL%%:*}-${CELL##*:}"

# Desktop, fisherman repo and commit come from tunaos.toml, never from a tag.
# The desktop is the flavor up to its first dash (gnome-hwe is gnome); the
# dispatcher rejects any name it does not know.
mapfile -t cfg < <(
	python3 - "${HERE}/.." "${CELL}" <<'PY'
import importlib.util
import sys
from pathlib import Path

root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
medium = c.installer_medium_policy()
primary = c.load(root / "tunaos.toml")
medium.cell(primary, sys.argv[2])
policy = primary["installer_medium"]
print(medium.desktop_of(sys.argv[2]))
print(policy["fisherman_repo"])
print(policy["fisherman_ref"])
PY
)
DESKTOP="${cfg[0]}" FISHERMAN_REPO="${cfg[1]}" FISHERMAN_REF="${cfg[2]}"

echo "podman build Containerfile.live (FROM $("${HERE}/resolve-cell-image.sh" "${CELL}")) -> ${TAG}"
echo "live: desktop ${DESKTOP}, fishermand ${FISHERMAN_REPO} @ ${FISHERMAN_REF}"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	"${HERE}/daemon/build-fishermand.sh" "${FISHERMAN_REPO}" "${FISHERMAN_REF}" /stage --dry-run
	"${HERE}/frontends/build-frontend.sh" "${DESKTOP}" /work --dry-run
	"${HERE}/frontends/install-frontend.sh" "${DESKTOP}" /stage --dry-run
	echo "(dry run: no image built)"
	exit 0
fi
podman build --pull=never -f "${HERE}/Containerfile.live" \
	--build-arg "SOURCE_IMAGE=$("${HERE}/resolve-cell-image.sh" "${CELL}")" \
	--build-arg "DESKTOP=${DESKTOP}" \
	--build-arg "FISHERMAN_REPO=${FISHERMAN_REPO}" \
	--build-arg "FISHERMAN_REF=${FISHERMAN_REF}" \
	-t "${TAG}" "${HERE}"
