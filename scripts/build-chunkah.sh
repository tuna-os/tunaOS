#!/usr/bin/env bash
# Build the chunkah container image locally from upstream coreos/chunkah.
#
# Usage:
#   ./scripts/build-chunkah.sh              # build from coreos/chunkah
#   ./scripts/build-chunkah.sh /path/to/src # build from a local checkout
#
# The image is tagged as localhost/chunkah:latest.

set -euo pipefail

REPO_URL="https://github.com/coreos/chunkah.git"
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
# Use podman build (available in CI); fall back to buildah if podman isn't available
if command -v podman &>/dev/null; then
	podman build \
		--security-opt=label=disable \
		--skip-unused-stages=false \
		--tag "$TAG" \
		.
elif command -v buildah &>/dev/null; then
	buildah build \
		-v "$PWD:/run/src" --security-opt=label=disable \
		--skip-unused-stages=false \
		--tag "$TAG" \
		.
else
	echo "ERROR: neither podman nor buildah found" >&2
	exit 1
fi

echo ""
echo "✓ Built $TAG"
echo "  To use it in the pipeline, set:"
echo "    export CHUNKAH_IMAGE=$TAG"
