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
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

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
# Run 40025622951 used Podman 4.9.3; its cache parser adds explicit rw
# and the writable default twice. Buildah v1.33.7 has the same parser.
# Cache mounts default to writable, but bind mounts do not. Keep bind rw.
if command -v podman &>/dev/null; then
	builder=podman
elif command -v buildah &>/dev/null; then
	builder=buildah
else
	echo "ERROR: neither podman nor buildah found" >&2
	exit 1
fi
build_file="$PWD/Containerfile"
version="$("$builder" --version)"
case "$version" in
"podman version 4.9.3" | "buildah version 1.33.7 "*)
	compat_dir="$(mktemp -d /tmp/chunkah-containerfile-XXXXXX)"
	trap 'rm -rf "$compat_dir"' EXIT
	build_file="$compat_dir/Containerfile"
	python3 "$SCRIPT_DIR/chunkah-cache-compat.py" "$PWD/Containerfile" "$build_file"
	;;
esac
# This records mutable/local inputs; it does not turn them into a source pin.
source_sha="$(git rev-parse HEAD 2>/dev/null || true)"
if [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]]; then
	printf 'chunkah source repository HEAD: %s\n' "$source_sha"
else
	echo 'chunkah source repository HEAD: unavailable'
fi
printf 'chunkah original Containerfile SHA256: %s\n' "$(sha256sum Containerfile | cut -d ' ' -f 1)"
printf 'chunkah build Containerfile SHA256: %s\n' "$(sha256sum "$build_file" | cut -d ' ' -f 1)"
# Retain the builder-specific flags; do not broaden container privileges.
if [[ "$builder" == podman ]]; then
	podman build \
		--security-opt=label=disable \
		--skip-unused-stages=false \
		--file "$build_file" \
		--tag "$TAG" \
		.
else
	buildah build \
		-v "$PWD:/run/src" --security-opt=label=disable \
		--skip-unused-stages=false \
		--file "$build_file" \
		--tag "$TAG" \
		.
fi

echo ""
echo "✓ Built $TAG"
echo "  To use it in the pipeline, set:"
echo "    export CHUNKAH_IMAGE=$TAG"
