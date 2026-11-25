#!/usr/bin/env bash
# Build the frontend artifacts for one desktop (tunaOS#4905).
#
# Usage: installer-medium/frontends/build-frontend.sh DESKTOP OUTDIR [--dry-run]
#
# Runs frontends/DESKTOP/build.sh OUTDIR when the desktop has one, then exports
# MEDIUM_PAYLOAD=OUTDIR for install.sh. A desktop whose frontend needs no
# build (a prebuilt Flatpak, for example) has no build.sh and this is a no-op.
# Containerfile.live runs it in its payload stage, before install-frontend.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP="${1:?usage: build-frontend.sh DESKTOP OUTDIR [--dry-run]}"
OUT="${2:?usage: build-frontend.sh DESKTOP OUTDIR [--dry-run]}"
DRY_RUN="${3:-}"
FRONTENDS="${MEDIUM_FRONTENDS_DIR:-${HERE}}"

case "${DESKTOP}" in
gnome | kde | cosmic | niri | xfce | pantheon) ;;
*)
	echo "build-frontend: unknown desktop '${DESKTOP}'" >&2
	exit 1
	;;
esac
script="${FRONTENDS}/${DESKTOP}/build.sh"
if [[ ! -x "${script}" ]]; then
	echo "build-frontend: ${DESKTOP} has no build.sh; nothing to build"
	exit 0
fi
echo "build-frontend: ${script} ${OUT}"
[[ "${DRY_RUN}" = "--dry-run" ]] && exit 0
install -d "${OUT}"
"${script}" "${OUT}"
