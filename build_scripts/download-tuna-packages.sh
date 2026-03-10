#!/usr/bin/env bash
# Download TunaOS custom packages from GHCR using ORAS
# This script is called during tunaOS image builds to fetch custom RPM packages

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
REGISTRY="${REGISTRY:-ghcr.io}"
REPOSITORY="${REPOSITORY:-tuna-os/packages}"
CACHE_DIR="${TUNA_PACKAGES_CACHE:-/tmp/tuna-packages}"
PACKAGES_LIST="${PACKAGES_LIST:-${SCRIPT_DIR}/packages.list}"

# Determine architecture
ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        # Check if this is x86_64_v2 capable (AlmaLinux Kitten uses this)
        if grep -q "alma" /etc/os-release 2>/dev/null && \
           grep -q "Kitten" /etc/os-release 2>/dev/null; then
            ARCH="x86_64_v2"
        else
            ARCH="x86_64"
        fi
        ;;
    aarch64)
        ARCH="aarch64"
        ;;
    *)
        echo "Warning: Unsupported architecture: ${ARCH}, using x86_64" >&2
        ARCH="x86_64"
        ;;
esac

echo "TunaOS Package Downloader"
echo "========================"
echo "Architecture: ${ARCH}"
echo "Registry: ${REGISTRY}"
echo "Repository: ${REPOSITORY}"
echo "Cache: ${CACHE_DIR}"
echo

# Install oras if not present
if ! command -v oras &>/dev/null; then
    echo "Installing ORAS CLI..."
    ORAS_VERSION="1.1.0"
    ORAS_TMP="/tmp/oras"
    mkdir -p "${ORAS_TMP}"
    curl -sL "https://github.com/oras-project/oras/releases/download/v${ORAS_VERSION}/oras_${ORAS_VERSION}_linux_amd64.tar.gz" \
        | tar xz -C "${ORAS_TMP}"
    install -m 755 "${ORAS_TMP}/oras" /usr/local/bin/oras
    rm -rf "${ORAS_TMP}"
    echo "✓ ORAS installed"
fi

# Create cache directory
mkdir -p "${CACHE_DIR}"

# Check if packages list exists
if [ ! -f "${PACKAGES_LIST}" ]; then
    echo "Error: Packages list not found: ${PACKAGES_LIST}" >&2
    echo "Create ${PACKAGES_LIST} with format: package-name:version-release[:arch]" >&2
    exit 1
fi

# Read packages list and download
DOWNLOAD_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0

while IFS=: read -r PACKAGE_NAME VERSION_RELEASE PKG_ARCH || [ -n "${PACKAGE_NAME}" ]; do
    # Skip comments and empty lines
    [[ "${PACKAGE_NAME}" =~ ^#.*$ || -z "${PACKAGE_NAME}" ]] && continue
    
    # Trim whitespace
    PACKAGE_NAME="${PACKAGE_NAME## }"
    PACKAGE_NAME="${PACKAGE_NAME%% }"
    VERSION_RELEASE="${VERSION_RELEASE## }"
    VERSION_RELEASE="${VERSION_RELEASE%% }"
    
    # Use detected arch if not specified in list
    if [ -z "${PKG_ARCH}" ]; then
        PKG_ARCH="${ARCH}"
    else
        PKG_ARCH="${PKG_ARCH## }"
        PKG_ARCH="${PKG_ARCH%% }"
    fi
    
    # Construct ORAS reference
    TAG="${VERSION_RELEASE}-${PKG_ARCH}-el10"
    FULL_REF="${REGISTRY}/${REPOSITORY}/${PACKAGE_NAME}:${TAG}"
    
    # Check if already cached
    if find "${CACHE_DIR}" -name "${PACKAGE_NAME}-${VERSION_RELEASE}*.${PKG_ARCH}.rpm" -type f | grep -q .; then
        echo "  ✓ ${PACKAGE_NAME} ${VERSION_RELEASE} (${PKG_ARCH}) - cached"
        ((SKIP_COUNT++)) || true
        continue
    fi
    
    echo "  ⬇ Downloading ${PACKAGE_NAME} ${VERSION_RELEASE} (${PKG_ARCH})..."
    
    # Pull with ORAS
    cd "${CACHE_DIR}"
    if oras pull "${FULL_REF}" 2>/dev/null; then
        ((DOWNLOAD_COUNT++)) || true
        echo "    ✓ Downloaded"
    else
        # Some upstream packages (e.g. tailscale) only publish x86_64, not x86_64_v2.
        if [ "${PKG_ARCH}" = "x86_64_v2" ]; then
            FALLBACK_TAG="${VERSION_RELEASE}-x86_64-el10"
            FALLBACK_REF="${REGISTRY}/${REPOSITORY}/${PACKAGE_NAME}:${FALLBACK_TAG}"
            echo "    ! ${FULL_REF} not found, trying fallback: ${FALLBACK_REF}"
            if oras pull "${FALLBACK_REF}" 2>/dev/null; then
                ((DOWNLOAD_COUNT++)) || true
                echo "    ✓ Downloaded via x86_64 fallback"
            else
                echo "    ✗ Failed to download: ${FULL_REF} (and fallback ${FALLBACK_REF})" >&2
                ((FAIL_COUNT++)) || true
            fi
        else
            echo "    ✗ Failed to download: ${FULL_REF}" >&2
            ((FAIL_COUNT++)) || true
        fi
    fi
    cd - >/dev/null
    
done < "${PACKAGES_LIST}"

echo
echo "Summary"
echo "======="
echo "Downloaded: ${DOWNLOAD_COUNT}"
echo "Cached: ${SKIP_COUNT}"
echo "Failed: ${FAIL_COUNT}"
echo

# List downloaded packages
echo "Available packages in cache:"
ls -lh "${CACHE_DIR}"/*.rpm 2>/dev/null || echo "  (none)"

if [ ${FAIL_COUNT} -gt 0 ]; then
    echo
    echo "Warning: ${FAIL_COUNT} package(s) failed to download" >&2
    echo "Build may fail if these packages are required" >&2
    exit 1
fi

echo
echo "✓ Package download complete"
echo "Packages available in: ${CACHE_DIR}"
