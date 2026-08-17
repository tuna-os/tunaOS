#!/usr/bin/env bash
# Populate the fishing-pole theme's numbered frame contract at image-build
# time. The checked-in 0001 PNG is the source asset; symlinks keep the theme
# compatible with its Plymouth script without storing 57 duplicate blobs in
# the repository or final image layer.

set -euo pipefail

THEME_DIR="${1:?usage: $0 THEME_DIR}"
SOURCE="${THEME_DIR}/fishing-pole-0001.png"
FRAME_COUNT="${FISHING_POLE_FRAME_COUNT:-58}"

[[ -s "${SOURCE}" ]] || {
	echo "fishing-pole source frame is missing: ${SOURCE}" >&2
	exit 1
}

for ((frame = 2; frame <= FRAME_COUNT; frame++)); do
	name="${THEME_DIR}/fishing-pole-$(printf '%04d' "${frame}").png"
	ln -sfn "fishing-pole-0001.png" "${name}"
done
