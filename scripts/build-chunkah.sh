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

# Podman 4.9 / Buildah 1.33 (Ubuntu 24.04 runners) already add an implicit rw
# to every cache mount, so chunkah's `--mount=type=cache,rw,...` is rejected
# with `invalid options "rw, shared, rw, bind", can only specify 1 'rw' or 'ro'
# option` (#3809). Cache mounts are writable by default on every version, so
# build from a copy of the Containerfile with the redundant `rw` dropped from
# cache mounts only. Bind mounts (`--mount=type=bind,...,rw`) are untouched:
# they are read-only unless rw is explicit.
BUILD_FILE="$(mktemp /tmp/chunkah-containerfile-XXXXXX)"
trap 'rm -f "$BUILD_FILE"' EXIT
sed -E 's/(--mount=type=cache[^[:space:]]*),rw([,[:space:]]|$)/\1\2/g' Containerfile >"$BUILD_FILE"

# Use podman build (available in CI); fall back to buildah if podman isn't available
if command -v podman &>/dev/null; then
	podman build \
		--security-opt=label=disable \
		--skip-unused-stages=false \
		--file "$BUILD_FILE" \
		--tag "$TAG" \
		.
elif command -v buildah &>/dev/null; then
	buildah build \
		-v "$PWD:/run/src" --security-opt=label=disable \
		--skip-unused-stages=false \
		--file "$BUILD_FILE" \
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
