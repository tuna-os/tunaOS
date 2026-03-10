#!/usr/bin/env bash

set -euo pipefail

# Compare TunaOS variant containers with their upstream equivalents
# Usage: compare-with-upstream.sh <variant> <flavor> <upstream-image>

variant="${1:-}"
flavor="${2:-base}"
upstream_image="${3:-}"

if [[ -z "$variant" ]] || [[ -z "$upstream_image" ]]; then
    echo "Usage: $0 <variant> <flavor> <upstream-image>"
    echo "Example: $0 skipjack base ghcr.io/ublue-os/bluefin-lts:latest"
    echo "Example: $0 bonito-kde base ghcr.io/ublue-os/aurora:latest"
    exit 1
fi

TUNAOS_IMAGE="localhost/tunaos/${variant}:${flavor}-latest"
UPSTREAM_IMAGE="$upstream_image"

echo "========================================"
echo "Comparing TunaOS with Upstream"
echo "========================================"
echo "TunaOS Image:   $TUNAOS_IMAGE"
echo "Upstream Image: $UPSTREAM_IMAGE"
echo "========================================"
echo ""

# Check if TunaOS image exists locally
if ! podman image exists "$TUNAOS_IMAGE"; then
    echo "ERROR: TunaOS image not found: $TUNAOS_IMAGE"
    echo "Please build it first with: just build $variant $flavor"
    exit 1
fi

# Pull upstream image if not present
if ! podman image exists "$UPSTREAM_IMAGE"; then
    echo "Pulling upstream image: $UPSTREAM_IMAGE"
    podman pull "$UPSTREAM_IMAGE"
fi

# Create temporary directory for comparison
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

TUNAOS_DIR="$TEMP_DIR/tunaos"
UPSTREAM_DIR="$TEMP_DIR/upstream"

mkdir -p "$TUNAOS_DIR" "$UPSTREAM_DIR"

echo "Extracting filesystem contents..."
echo ""

# Extract key directories from both images
# Focus on /usr and /etc as those contain the system configuration
podman run --rm -v "$TUNAOS_DIR:/extract:Z" "$TUNAOS_IMAGE" bash -c '
    mkdir -p /extract/usr /extract/etc
    cp -a /usr/share /extract/usr/ 2>/dev/null || true
    cp -a /usr/lib /extract/usr/ 2>/dev/null || true
    cp -a /usr/libexec /extract/usr/ 2>/dev/null || true
    cp -a /usr/bin /extract/usr/ 2>/dev/null || true
    cp -a /etc /extract/
' || echo "Warning: Some directories may not have been extracted from TunaOS"

podman run --rm -v "$UPSTREAM_DIR:/extract:Z" "$UPSTREAM_IMAGE" bash -c '
    mkdir -p /extract/usr /extract/etc
    cp -a /usr/share /extract/usr/ 2>/dev/null || true
    cp -a /usr/lib /extract/usr/ 2>/dev/null || true
    cp -a /usr/libexec /extract/usr/ 2>/dev/null || true
    cp -a /usr/bin /extract/usr/ 2>/dev/null || true
    cp -a /etc /extract/
' || echo "Warning: Some directories may not have been extracted from Upstream"

echo "========================================"
echo "File Count Comparison"
echo "========================================"
echo ""

echo "TunaOS /usr file count:"
find "$TUNAOS_DIR/usr" -type f 2>/dev/null | wc -l

echo "Upstream /usr file count:"
find "$UPSTREAM_DIR/usr" -type f 2>/dev/null | wc -l

echo ""
echo "TunaOS /etc file count:"
find "$TUNAOS_DIR/etc" -type f 2>/dev/null | wc -l

echo "Upstream /etc file count:"
find "$UPSTREAM_DIR/etc" -type f 2>/dev/null | wc -l

echo ""
echo "========================================"
echo "Unique Files in TunaOS (not in upstream)"
echo "========================================"
echo ""

(cd "$TUNAOS_DIR" && find . -type f | sort) > "$TEMP_DIR/tunaos-files.txt"
(cd "$UPSTREAM_DIR" && find . -type f | sort) > "$TEMP_DIR/upstream-files.txt"

comm -23 "$TEMP_DIR/tunaos-files.txt" "$TEMP_DIR/upstream-files.txt" | head -50
UNIQUE_TUNAOS=$(comm -23 "$TEMP_DIR/tunaos-files.txt" "$TEMP_DIR/upstream-files.txt" | wc -l)
echo ""
echo "Total unique files in TunaOS: $UNIQUE_TUNAOS"

echo ""
echo "========================================"
echo "Unique Files in Upstream (not in TunaOS)"
echo "========================================"
echo ""

comm -13 "$TEMP_DIR/tunaos-files.txt" "$TEMP_DIR/upstream-files.txt" | head -50
UNIQUE_UPSTREAM=$(comm -13 "$TEMP_DIR/tunaos-files.txt" "$TEMP_DIR/upstream-files.txt" | wc -l)
echo ""
echo "Total unique files in Upstream: $UNIQUE_UPSTREAM"

echo ""
echo "========================================"
echo "Package Comparison"
echo "========================================"
echo ""

echo "Extracting package lists..."
podman run --rm "$TUNAOS_IMAGE" rpm -qa | sort > "$TEMP_DIR/tunaos-packages.txt"
podman run --rm "$UPSTREAM_IMAGE" rpm -qa | sort > "$TEMP_DIR/upstream-packages.txt"

echo ""
echo "Packages in TunaOS but not Upstream (first 30):"
comm -23 "$TEMP_DIR/tunaos-packages.txt" "$TEMP_DIR/upstream-packages.txt" | head -30
UNIQUE_PKG_TUNAOS=$(comm -23 "$TEMP_DIR/tunaos-packages.txt" "$TEMP_DIR/upstream-packages.txt" | wc -l)
echo ""
echo "Total: $UNIQUE_PKG_TUNAOS packages"

echo ""
echo "Packages in Upstream but not TunaOS (first 30):"
comm -13 "$TEMP_DIR/tunaos-packages.txt" "$TEMP_DIR/upstream-packages.txt" | head -30
UNIQUE_PKG_UPSTREAM=$(comm -13 "$TEMP_DIR/tunaos-packages.txt" "$TEMP_DIR/upstream-packages.txt" | wc -l)
echo ""
echo "Total: $UNIQUE_PKG_UPSTREAM packages"

echo ""
echo "========================================"
echo "Summary"
echo "========================================"
echo "TunaOS has $UNIQUE_TUNAOS unique files compared to upstream"
echo "Upstream has $UNIQUE_UPSTREAM unique files compared to TunaOS"
echo "TunaOS has $UNIQUE_PKG_TUNAOS unique packages compared to upstream"
echo "Upstream has $UNIQUE_PKG_UPSTREAM unique packages compared to TunaOS"
echo ""
echo "Detailed file lists saved to:"
echo "  $TEMP_DIR/tunaos-files.txt"
echo "  $TEMP_DIR/upstream-files.txt"
echo "  $TEMP_DIR/tunaos-packages.txt"
echo "  $TEMP_DIR/upstream-packages.txt"
echo ""
echo "To keep these files, copy from: $TEMP_DIR"
