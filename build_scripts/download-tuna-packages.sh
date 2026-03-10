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

# Setup ORAS with multiple fallback strategies
ORAS_CMD="oras"
ORAS_WRAPPER=""

if ! command -v oras &>/dev/null; then
    echo "ORAS CLI not found. Attempting installation with fallbacks..."
    
    # Strategy 1: Try homebrew
    if command -v brew &>/dev/null; then
        echo "  → Trying homebrew install..."
        if brew install oras 2>/dev/null; then
            echo "  ✓ ORAS installed via homebrew"
            ORAS_CMD="oras"
        else
            echo "  ✗ Homebrew install failed"
        fi
    fi
    
    # Strategy 2: Try user-local installation (~/.local/bin)
    if ! command -v oras &>/dev/null; then
        echo "  → Trying user-local installation to ~/.local/bin..."
        ORAS_VERSION="1.1.0"
        ORAS_TMP="/tmp/oras-$$"
        ORAS_ARCH="amd64"
        [ "$(uname -m)" = "aarch64" ] && ORAS_ARCH="arm64"
        
        if mkdir -p "${ORAS_TMP}" && \
           curl -sL "https://github.com/oras-project/oras/releases/download/v${ORAS_VERSION}/oras_${ORAS_VERSION}_linux_${ORAS_ARCH}.tar.gz" \
               | tar xz -C "${ORAS_TMP}" 2>/dev/null; then
            
            mkdir -p "$HOME/.local/bin"
            if mv "${ORAS_TMP}/oras" "$HOME/.local/bin/oras" 2>/dev/null && \
               chmod +x "$HOME/.local/bin/oras"; then
                export PATH="$HOME/.local/bin:$PATH"
                echo "  ✓ ORAS installed to ~/.local/bin"
                ORAS_CMD="$HOME/.local/bin/oras"
            else
                echo "  ✗ Failed to move ORAS binary"
            fi
        else
            echo "  ✗ Failed to download ORAS"
        fi
        rm -rf "${ORAS_TMP}"
    fi
    
    # Strategy 3: Use podman container as wrapper
    if ! command -v "${ORAS_CMD}" &>/dev/null && command -v podman &>/dev/null; then
        echo "  → Using podman container for ORAS..."
        ORAS_CMD="podman"
        ORAS_WRAPPER="run --rm -v ${CACHE_DIR}:${CACHE_DIR} ghcr.io/oras-project/oras:v1.1.0"
        echo "  ✓ Will use podman container: ghcr.io/oras-project/oras:v1.1.0"
    fi
    
    # Final check
    if ! command -v "${ORAS_CMD%% *}" &>/dev/null && [ -z "${ORAS_WRAPPER}" ]; then
        echo "✗ Failed to install or find ORAS CLI" >&2
        echo "  Please manually install ORAS:" >&2
        echo "    - Via homebrew: brew install oras" >&2
        echo "    - Via GitHub: https://github.com/oras-project/oras/releases" >&2
        exit 1
    fi
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
    
    # Check if already cached (support both dash and underscore filename separators)
    if find "${CACHE_DIR}" -name "${PACKAGE_NAME}[-_]*.rpm" -not -name "*.src.rpm" -type f | grep -q .; then
        echo "  ✓ ${PACKAGE_NAME} ${VERSION_RELEASE} (${PKG_ARCH}) - cached"
        ((SKIP_COUNT++)) || true
        continue
    fi
    
    echo "  ⬇ Downloading ${PACKAGE_NAME} ${VERSION_RELEASE} (${PKG_ARCH})..."
    
    # Pull with ORAS (using appropriate method: direct, homebrew, or podman)
    cd "${CACHE_DIR}"
    ORAS_PULL_CMD="${ORAS_CMD}"
    [ -n "${ORAS_WRAPPER}" ] && ORAS_PULL_CMD="${ORAS_WRAPPER} oras"
    
    if ${ORAS_PULL_CMD} pull "${FULL_REF}" 2>/dev/null; then
        ((DOWNLOAD_COUNT++)) || true
        echo "    ✓ Downloaded"
    else
        # Some upstream packages (e.g. tailscale) only publish x86_64, not x86_64_v2.
        if [ "${PKG_ARCH}" = "x86_64_v2" ]; then
            FALLBACK_TAG="${VERSION_RELEASE}-x86_64-el10"
            FALLBACK_REF="${REGISTRY}/${REPOSITORY}/${PACKAGE_NAME}:${FALLBACK_TAG}"
            echo "    ! ${FULL_REF} not found, trying fallback: ${FALLBACK_REF}"
            if ${ORAS_PULL_CMD} pull "${FALLBACK_REF}" 2>/dev/null; then
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
