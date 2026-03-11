#!/usr/bin/env bash
# Build the chunkah container image locally from the tuna-os fork.
#
# Usage:
#   ./scripts/build-chunkah.sh              # build from tuna-os/chunkah
#   ./scripts/build-chunkah.sh /path/to/src # build from a local checkout
#
# The image is tagged as localhost/chunkah:latest.

set -euo pipefail

REPO_URL="https://github.com/tuna-os/chunkah.git"
TAG="localhost/chunkah:latest"

if [[ -n "${1:-}" ]] && [[ -d "$1" ]]; then
	SRC_DIR="$1"
	echo "Building chunkah from local source: $SRC_DIR"
else
	SRC_DIR=$(mktemp -d /tmp/chunkah-build-XXXXXX)
	echo "Cloning $REPO_URL -> $SRC_DIR"
	git clone --depth=1 "$REPO_URL" "$SRC_DIR"
fi

echo "Building chunkah image..."
cd "$SRC_DIR"
# Use buildah build with the required volume mount for out.ociarchive
buildah build \
	-v "$PWD:/run/src" --security-opt=label=disable \
	--skip-unused-stages=false \
	--tag "$TAG" \
	.

echo ""
echo "✓ Built $TAG"
echo "  To use it in the pipeline, set:"
echo "    export CHUNKAH_IMAGE=$TAG"
