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

echo "podman build Containerfile.live (FROM $("${HERE}/resolve-cell-image.sh" "${CELL}")) -> ${TAG}"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "(dry run: no image built)"
	exit 0
fi
podman build --pull=never -f "${HERE}/Containerfile.live" \
	--build-arg "SOURCE_IMAGE=$("${HERE}/resolve-cell-image.sh" "${CELL}")" \
	-t "${TAG}" "${HERE}"
