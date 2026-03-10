# --- Environment Variables & Exports ---
# ==============================================================================
#  PACKAGE MANAGEMENT (TunaOS Custom Packages)
# ==============================================================================

# Download/sync TunaOS custom packages from GHCR to local cache
sync-packages:
    #!/usr/bin/env bash
    chmod +x build_scripts/download-tuna-packages.sh
    echo "Syncing TunaOS custom packages from GHCR..."
    export TUNA_PACKAGES_CACHE="${HOME}/.cache/tuna-packages"
    mkdir -p "${TUNA_PACKAGES_CACHE}"
    build_scripts/download-tuna-packages.sh
    echo "✓ Packages synced to ${TUNA_PACKAGES_CACHE}"

# List available TunaOS custom packages and their versions
list-packages:
    #!/usr/bin/env bash
    CACHE_DIR="${HOME}/.cache/tuna-packages"
    if [ -d "${CACHE_DIR}" ] && [ -n "$(ls -A "${CACHE_DIR}"/*.rpm 2>/dev/null)" ]; then
        echo "TunaOS Custom Packages (cached):"
        echo "================================="
        for rpm in "${CACHE_DIR}"/*.rpm; do
            if [ -f "${rpm}" ]; then
                rpm -qip "${rpm}" 2>/dev/null | grep -E "^(Name|Version|Release|Architecture)" | sed 's/^/  /'
                echo ""
            fi
        done
    else
        echo "No packages in cache. Run 'just sync-packages' to download."
    fi
    echo ""
    echo "Configured packages (from packages.list):"
    echo "=========================================="
    if [ -f build_scripts/packages.list ]; then
        grep -v '^#' build_scripts/packages.list | grep -v '^[[:space:]]*$' || echo "  (none configured)"
    else
        echo "  packages.list not found"
    fi

# Clean local TunaOS package cache
clean-package-cache:
    #!/usr/bin/env bash
    CACHE_DIR="${HOME}/.cache/tuna-packages"
    echo "Cleaning TunaOS package cache..."
    if [ -d "${CACHE_DIR}" ]; then
        rm -rf "${CACHE_DIR}"
        echo "✓ Cache cleared: ${CACHE_DIR}"
    else
        echo "Cache directory does not exist: ${CACHE_DIR}"
    fi

export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export default_tag := env("DEFAULT_TAG", "latest")
export bib_image := env("BIB_IMAGE", "quay.io/centos-bootc/bootc-image-builder:latest")
export common_image := env("COMMON_IMAGE", "ghcr.io/projectbluefin/common")
export brew_image := env("BREW_IMAGE", "ghcr.io/ublue-os/brew")
export coreos_stable_version := env("COREOS_STABLE_VERSION", "42")
just := just_executable()
arch := arch()
export platform := env("PLATFORM", if arch == "x86_64" { if `rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; echo $?` == "0" { "linux/amd64/v2" } else { "linux/amd64" } } else if arch == "arm64" { "linux/arm64" } else if arch == "aarch64" { "linux/arm64" } else { error("Unsupported ARCH '" + arch + "'. Supported values are 'x86_64', 'aarch64', and 'arm64'.") })

# --- Default Base Image (for 'base' flavor builds) ---

export base_image := env("BASE_IMAGE", "quay.io/almalinuxorg/almalinux-bootc")
export base_image_tag := env("BASE_IMAGE_TAG", "10")

[private]
default:
    @{{ just }} --list

# Initialize and update git submodules
submodules:
    #!/usr/bin/env bash
    git submodule update --init --recursive

# Check Just Syntax
check:
    #!/usr/bin/env bash
    echo "Checking syntax of shell scripts..."
    /usr/bin/find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -iname "*.sh" -type f -exec shellcheck --exclude=SC1091 "{}" ";"
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.yaml" | while read -r file; do
        echo "Checking syntax: $file"
        yamllint -c ./.yamllint.yml "$file" || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.yml" | while read -r file; do
        echo "Checking syntax: $file"
        yamllint "$file" || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.json" | while read -r file; do
        echo "Checking syntax: $file"
        jq . "$file" > /dev/null || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.just" | while read -r file; do
        echo "Checking syntax: $file"
        just --unstable --fmt --check -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt --check -f Justfile

# Fix Just Syntax
fix:
    #!/usr/bin/env bash
    echo "Fixing syntax of shell scripts..."
        /usr/bin/find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -iname "*.sh" -type f -exec shfmt --write "{}" ";"
    find . -type f -name "*.just" | while read -r file; do
        echo "Checking syntax: $file"
        just --unstable --fmt -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt -f Justfile || { exit 1; }

clean:
    #!/usr/bin/env bash
    echo "Cleaning up build artifacts and images..."
    echo "Note: Preserving .rpm-cache for faster rebuilds. Use 'just clean-cache' to remove."
    rm -rf .build-logs
    sudo rm -rf .build/*
    echo "Removing local podman images for all variants and flavors..."
    variants=(yellowfin albacore bonito skipjack redfin)
    images=()
    for variant in "${variants[@]}"; do
        images+=("$variant")
        images+=("${variant}-hwe")
        images+=("${variant}-gdx")
        images+=("${variant}-gdx-hwe")
        images+=("${variant}-kde")
        images+=("${variant}-kde-hwe")
        images+=("${variant}-kde-gdx")
        images+=("${variant}-kde-gdx-hwe")
    done
    for img in "${images[@]}"; do
        podman rmi -f "localhost/${img}:latest" 2>/dev/null || true
    done
    for img in "${images[@]}"; do
        sudo podman rmi -f "localhost/${img}:latest" 2>/dev/null || true
    done

# Prune build caches (DNF/RPM cache directory shared across all variants)
clean-cache:
    #!/usr/bin/env bash
    echo "Pruning local build caches..."
    echo "Removing .rpm-cache directory..."
    rm -rf '.rpm-cache'
    echo "Cache cleanup complete."
    echo "Note: Podman BuildKit cache is separate. Use 'podman system prune --build-cache' if needed."

# ==============================================================================
#  BUILD PIPELINE
# ==============================================================================

# Check if yq is installed
[private]
_ensure-yq:
    #!/usr/bin/env bash
    if ! command -v yq &> /dev/null; then
        echo "Missing requirement: 'yq' is not installed."
        echo "Please install yq (e.g. 'brew install yq' or download from https://github.com/mikefarah/yq)"
        exit 1
    fi

# Private build engine. Now accepts final image name and brand as parameters.
# Note: enable_gdx parameter controls both GDX features and HWE (Hardware Enablement).
# When enable_gdx=1, ENABLE_HWE is set to 1 and coreos-stable akmods are used for
# When enable_hwe=1, coreos-stable akmods are used for

# NVIDIA drivers, ZFS modules, and the coreos/fedora kernel.
[private]
_build target_tag_with_version target_tag container_file base_image_for_build platform use_cache enable_gdx enable_hwe desktop_flavor *args: _ensure-yq
    #!/usr/bin/env bash
    set -euxo pipefail

    # Get image digests from image-versions.yaml
    common_image_sha=$(yq -r '.images[] | select(.name == "common") | .digest' image-versions.yaml)
    common_image_ref="{{ common_image }}@${common_image_sha}"
    brew_image_sha=$(yq -r '.images[] | select(.name == "brew") | .digest' image-versions.yaml)
    brew_image_ref="{{ brew_image }}@${brew_image_sha}"

    BUILD_ARGS=()
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME={{ target_tag }}")
    BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR={{ repo_organization }}")
    BUILD_ARGS+=("--build-arg" "BASE_IMAGE={{ base_image_for_build }}")
    BUILD_ARGS+=("--build-arg" "COMMON_IMAGE_REF=${common_image_ref}")
    BUILD_ARGS+=("--build-arg" "BREW_IMAGE_REF=${brew_image_ref}")
    # GDX or HWE builds use coreos akmods for HWE (Hardware Enablement)
    BUILD_ARGS+=("--build-arg" "ENABLE_HWE={{ enable_hwe }}")
    BUILD_ARGS+=("--build-arg" "ENABLE_GDX={{ enable_gdx }}")
    BUILD_ARGS+=("--build-arg" "DESKTOP_FLAVOR={{ desktop_flavor }}")

    # Determine AKMODS_BASE based on target variant/flavor and HWE status.
    # HWE: always use ublue-os coreos akmods (with coreos kernel).
    # Non-HWE Alma: use tuna-os akmods for zfs; uses Alma repos for NVIDIA (no akmods-nvidia-open).
    # Non-HWE others: use ublue-os and appropriate version tag.
    akmods_base="ghcr.io/ublue-os"
    if [[ "{{ target_tag }}" == albacore* ]] || [[ "{{ target_tag }}" == yellowfin* ]] || [[ "{{ target_tag }}" == almalinux* ]] || [[ "{{ target_tag }}" == redfin* ]]; then
        if [[ "{{ enable_hwe }}" != "1" ]]; then
            akmods_base="ghcr.io/tuna-os"
        fi
    fi
    BUILD_ARGS+=("--build-arg" "AKMODS_BASE=${akmods_base}")

    # Select akmods source tag for mounted ZFS/NVIDIA images.
    # HWE always uses coreos-stable for compatibility with coreos kernel.
    # Non-HWE Alma uses almalinux-10 for zfs (NVIDIA from Alma repos, uses coreos-stable nvidia image but won't mount it).
    if [[ "{{ enable_hwe }}" -eq "1" ]]; then
        BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=coreos-stable-{{ coreos_stable_version }}")
        BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=coreos-stable-{{ coreos_stable_version }}")
    else
        if [[ "{{ target_tag }}" == albacore* ]] || [[ "{{ target_tag }}" == yellowfin* ]] || [[ "{{ target_tag }}" == almalinux* ]] || [[ "{{ target_tag }}" == redfin* ]]; then
            BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=almalinux-10")
            # Non-HWE Alma: use coreos-stable for nvidia image (optional mount, won't be used)
            BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=coreos-stable-{{ coreos_stable_version }}")
        else
            BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=centos-10")
            BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=centos-10")
        fi
    fi
    # Pass build context to Containerfile for conditional handling
    BUILD_ARGS+=("--build-arg" "ENABLE_HWE={{ enable_hwe }}")
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME_VARIANT={{ target_tag }}")

    if [[ -z "$(git status -s)" ]]; then
        BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
    fi
    echo "{{ use_cache }}"
    if [[ "{{ use_cache }}" == "1" ]]; then
        # Use per-variant cache with deduplication for parallel builds
        readarray -t CACHE_MOUNTS < <(./scripts/setup-build-cache.sh "{{ target_tag }}")
        BUILD_ARGS+=("${CACHE_MOUNTS[@]}")
    fi

    # Determine build target for multi-stage Containerfiles.
    # GNOME is default; KDE and Niri are selected explicitly.
    # no-DE intermediates map to the base stages in HWE/GDX Containerfiles.
    BUILD_TARGET="gnome"
    if [[ "{{ desktop_flavor }}" == "kde" ]]; then
        BUILD_TARGET="kde"
    elif [[ "{{ desktop_flavor }}" == "niri" ]]; then
        BUILD_TARGET="niri"
    elif [[ "{{ desktop_flavor }}" == "base-no-de" ]]; then
        BUILD_TARGET="base-no-de"
    elif [[ "{{ desktop_flavor }}" == "hwe-base-node" ]]; then
        BUILD_TARGET="hwe-base"
    elif [[ "{{ desktop_flavor }}" == "gdx-base-node" ]]; then
        BUILD_TARGET="gdx-base"
    fi

    podman build \
        --dns=8.8.8.8 \
        --platform "{{ platform }}" \
        --target="${BUILD_TARGET}" \
        "${BUILD_ARGS[@]}" \
        {{ args }} \
        --pull=newer \
        --tag "{{ target_tag_with_version }}" \
        --file "{{ container_file }}" \
        .

# --- Unified Build Pipeline ---
# This rule now handles both local and CI builds.
# For CI builds, pass `is_ci=true` and `image_name` as the final tag.
# For local builds, pass `is_ci=0` (or omit) and `variant` as the local name.
#
# Usage (local): just build <variant> [flavor]
# Example: just build yellowfin kde
#
# Usage (CI): just build image_name=<final_name> variant=<base_os> is_ci=true [flavor]

# Example: just build image_name=albacore variant=almalinux is_ci=true kde-gdx
build variant='albacore' flavor='base' platform=`echo $platform` is_ci="0" tag='latest' chain_base_image='':
    #!/usr/bin/env bash
    set -euo pipefail

    # Initialize submodules locally (CI uses actions/checkout with submodules: recursive)
    if [[ "{{ is_ci }}" != "1" ]]; then
        git submodule update --init --recursive
    fi

    # ANSI color codes
    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m' # No Color

    echo -e "${BLUE}===============================================================${NC}"
    echo -e "${GREEN}Build config:${NC}"
    echo -e "  Variant: ${YELLOW}{{ variant }}${NC}"
    echo -e "  Flavor: ${YELLOW}{{ flavor }}${NC}"
    echo -e "  Platform: ${YELLOW}{{ platform }}${NC}"
    echo -e "  Is CI: ${YELLOW}{{ is_ci }}${NC}"
    echo -e "  Tag: ${YELLOW}{{ tag }}${NC}"
    echo -e "  Chain Base Image: ${YELLOW}{{ chain_base_image }}${NC}"
    echo -e "${BLUE}===============================================================${NC}"


    BASE_FOR_BUILD=""
    CONTAINERFILE="Containerfile"
    DESKTOP_FLAVOR="gnome"

    case "{{ flavor }}" in
        "base")
            BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
            ;;
        "hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.hwe"
            ;;
        "gdx")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            ;;
        "gdx-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-hwe:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}-hwe:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            ;;
        "hwe-base-node")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.hwe"
            DESKTOP_FLAVOR="hwe-base-node"
            ;;
        "gdx-base-node")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="gdx-base-node"
            ;;
        "kde")
            BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
            CONTAINERFILE="Containerfile"
            DESKTOP_FLAVOR="kde"
            ;;
        "kde-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-kde:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}-kde:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.hwe"
            DESKTOP_FLAVOR="kde"
            ;;
        "kde-gdx")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-kde:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}-kde:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="kde"
            ;;
        "kde-gdx-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-kde-hwe:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}-kde-hwe:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="kde"
            ;;
        "niri")
            BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
            CONTAINERFILE="Containerfile"
            DESKTOP_FLAVOR="niri"
            ;;
        "niri-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-niri:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}-niri:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.hwe"
            DESKTOP_FLAVOR="niri"
            ;;
        "niri-gdx")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-niri:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}-niri:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="niri"
            ;;
        "niri-gdx-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-niri-hwe:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}-niri-hwe:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="niri"
            ;;
        "all")
            just build {{ variant }} base
            just build {{ variant }} hwe
            just build {{ variant }} gdx
            just build {{ variant }} hwe-base-node
            just build {{ variant }} gdx-base-node
            just build {{ variant }} gdx-hwe
            just build {{ variant }} kde
            just build {{ variant }} kde-hwe
            just build {{ variant }} kde-gdx
            just build {{ variant }} kde-gdx-hwe
            just build {{ variant }} niri
            just build {{ variant }} niri-hwe
            just build {{ variant }} niri-gdx
            just build {{ variant }} niri-gdx-hwe
            exit 0
            ;;
        *)
            echo "Unknown flavor '{{ flavor }}'. Valid options are: base, hwe, gdx, hwe-base-node, gdx-base-node, gdx-hwe, kde, kde-hwe, kde-gdx, kde-gdx-hwe, niri, niri-hwe, niri-gdx, niri-gdx-hwe, all."
            exit 1
            ;;
    esac

    # Allow workflow callers to chain from an explicit parent image.
    if [[ -n "{{ chain_base_image }}" ]] && [[ "{{ flavor }}" != "base" ]]; then
        BASE_FOR_BUILD="{{ chain_base_image }}"
    fi

    TARGET_TAG={{ variant }}
    if [[ "{{ flavor }}" != "base" ]]; then
        TARGET_TAG+="-{{ flavor }}"
    fi
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:{{ tag }}"

    # Determine HWE flag - hwe and gdx flavors always use coreos akmods
    ENABLE_HWE="0"
    if [[ "{{ flavor }}" == "hwe" ]] || [[ "{{ flavor }}" == "hwe-base-node" ]] || [[ "{{ flavor }}" == "gdx-hwe" ]] || [[ "{{ flavor }}" == "kde-hwe" ]] || [[ "{{ flavor }}" == "kde-gdx-hwe" ]] || [[ "{{ flavor }}" == "niri-hwe" ]] || [[ "{{ flavor }}" == "niri-gdx-hwe" ]]; then
        ENABLE_HWE="1"
    fi

    # Determine GDX flag
    ENABLE_GDX="0"
    if [[ "{{ flavor }}" == "gdx" ]] || [[ "{{ flavor }}" == "gdx-base-node" ]] || [[ "{{ flavor }}" == "kde-gdx" ]] || [[ "{{ flavor }}" == "gdx-hwe" ]] || [[ "{{ flavor }}" == "kde-gdx-hwe" ]] || [[ "{{ flavor }}" == "niri-gdx" ]] || [[ "{{ flavor }}" == "niri-gdx-hwe" ]]; then
        ENABLE_GDX="1"
    fi

    echo -e "${BLUE}================================================================${NC}"
    echo -e "${GREEN}Building image with the following parameters:${NC}"
    echo -e "  Target Tag: ${YELLOW}${TARGET_TAG_WITH_VERSION}${NC}"
    echo -e "  Variant: ${YELLOW}{{ variant }}${NC}"
    echo -e "  Containerfile: ${YELLOW}${CONTAINERFILE}${NC}"
    echo -e "  Base Image for Build: ${YELLOW}${BASE_FOR_BUILD}${NC}"
    echo -e "  Platform: ${YELLOW}{{ platform }}${NC}"
    echo -e "  is_ci: ${YELLOW}{{ is_ci }}${NC}"
    echo -e "  Desktop Flavor: ${YELLOW}${DESKTOP_FLAVOR}${NC}"
    echo -e "  Enable HWE (uses coreos akmods): ${YELLOW}${ENABLE_HWE}${NC}"
    echo -e "  Enable GDX: ${YELLOW}${ENABLE_GDX}${NC}"
    echo -e "${BLUE}================================================================${NC}"

    if [[ "{{ is_ci }}" == "0" ]]; then
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "{{ platform }}" "1" "${ENABLE_GDX}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}"
        # Chunkify the built image for optimal layer distribution
        {{ just }} chunkify "${TARGET_TAG_WITH_VERSION}"
        # Sync cache after successful local build for deduplication
        ./scripts/sync-build-cache.sh "${TARGET_TAG}" || true
    else
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "{{ platform }}" "0" "${ENABLE_GDX}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}"
    fi

yellowfin variant='base':
    just build yellowfin {{ variant }}

albacore variant='base':
    just build albacore {{ variant }}

skipjack variant='base':
    just build skipjack {{ variant }}

bonito variant='base':
    just build bonito {{ variant }}

# NOTE: redfin requires a Red Hat account authenticated to registry.redhat.io.

# Images cannot be published publicly due to the RHEL EULA. See docs/rhel-setup.md.
redfin variant='base':
    just build redfin {{ variant }}

# Build full GNOME chain for a variant: base → hwe → gdx → gdx-hwe
build-chain variant:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Building full chain for {{ variant }}: base → hwe → gdx → gdx-hwe"
    just build {{ variant }} base
    just build {{ variant }} hwe
    # AlmaLinux non-HWE GDX may fail due to driver version lag in repos
    just build {{ variant }} gdx || echo "⚠ Warning: {{ variant }} GDX build failed (non-fatal for AlmaLinux variants)"
    just build {{ variant }} gdx-hwe
    echo "✓ Complete: {{ variant }} full chain built successfully"

# Build full KDE chain for a variant: kde → kde-hwe → kde-gdx → kde-gdx-hwe
build-chain-kde variant:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Building full KDE chain for {{ variant }}: kde → kde-hwe → kde-gdx → kde-gdx-hwe"
    just build {{ variant }} kde
    just build {{ variant }} kde-hwe
    # AlmaLinux non-HWE GDX may fail due to driver version lag in repos
    just build {{ variant }} kde-gdx || echo "⚠ Warning: {{ variant }} KDE-GDX build failed (non-fatal for AlmaLinux variants)"
    just build {{ variant }} kde-gdx-hwe
    echo "✓ Complete: {{ variant }} KDE chain built successfully"

# Build full Niri chain for a variant: niri → niri-hwe → niri-gdx → niri-gdx-hwe
build-chain-niri variant:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Building full Niri chain for {{ variant }}: niri → niri-hwe → niri-gdx → niri-gdx-hwe"
    just build {{ variant }} niri
    just build {{ variant }} niri-hwe
    # AlmaLinux non-HWE GDX may fail due to driver version lag in repos
    just build {{ variant }} niri-gdx || echo "⚠ Warning: {{ variant }} Niri-GDX build failed (non-fatal for AlmaLinux variants)"
    just build {{ variant }} niri-gdx-hwe
    echo "✓ Complete: {{ variant }} Niri chain built successfully"

# Build GNOME and KDE base in parallel (shares base-no-de layer)
build-de-parallel variant flavor='base':
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Building {{ variant }} {{ flavor }} with GNOME and KDE in parallel..."
    echo "Both will share the base-no-de layer for maximum efficiency"

    # Map flavor to actual DE names
    BASE_FLAVOR="{{ flavor }}"

    # Build both DEs in parallel - they share the base-no-de cached layer!
    just build {{ variant }} "${BASE_FLAVOR}" &
    GNOME_PID=$!

    # For KDE, prepend 'kde-' to flavor
    if [[ "${BASE_FLAVOR}" == "base" ]]; then
        KDE_FLAVOR="kde"
    else
        KDE_FLAVOR="kde-${BASE_FLAVOR}"
    fi
    just build {{ variant }} "${KDE_FLAVOR}" &
    KDE_PID=$!

    wait $GNOME_PID $KDE_PID
    echo "✓ Complete: {{ variant }} ${BASE_FLAVOR} (GNOME) and ${KDE_FLAVOR} built successfully"

# Build all stable variants in parallel (each doing full chain)

# Warning: Very resource intensive! Builds yellowfin, albacore, and skipjack simultaneously
build-all-parallel:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Building all stable variants in parallel..."
    just build-chain yellowfin &
    just build-chain albacore &
    just build-chain skipjack &
    wait
    echo "✓ All stable variants built"

# Build all variants including experimental (bonito, bonito-rawhide)
build-all-parallel-experimental:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Building all variants (including experimental) in parallel..."
    just build-chain yellowfin &
    just build-chain albacore &
    just build-chain skipjack &
    just build-chain bonito &
    just build-chain bonito-rawhide &
    wait
    echo "✓ All variants (including experimental) built"

build-all-base:
    #!/usr/bin/env bash
    set -euo pipefail
    bash ./scripts/build-all-images.sh --base-only --include-experimental

build-all:
    #!/usr/bin/env bash
    bash ./scripts/build-all-images.sh --include-kde

build-all-experimental:
    #!/usr/bin/env bash
    bash ./scripts/build-all-images.sh --include-experimental

# ── Chunkah ──────────────────────────────────────────────────────────

# Use the pre-built chunkah image from quay.io
chunkify image_ref:
    #!/usr/bin/env bash
    set -euo pipefail

    # Use sudo unless already root (CI runners are root)
    SUDO_CMD=""
    if [ "$(id -u)" -ne 0 ]; then
        SUDO_CMD="sudo"
    fi

    echo "==> Chunkifying {{ image_ref }}..."

    # Get config from existing image
    CONFIG=$($SUDO_CMD podman inspect "{{ image_ref }}")

    # Run chunkah (default 64 layers) and pipe to podman load
    # Uses --mount=type=image to expose the source image content to chunkah
    # Note: We need --privileged for some podman-in-podman/mount scenarios or just standard access
    LOADED=$($SUDO_CMD podman run --rm \
        --security-opt label=type:unconfined_t \
        --mount=type=image,src="{{ image_ref }}",dest=/chunkah \
        -e "CHUNKAH_CONFIG_STR=$CONFIG" \
        quay.io/jlebon/chunkah:latest build | $SUDO_CMD podman load)

    echo "$LOADED"

    # Parse the loaded image reference
    NEW_REF=$(echo "$LOADED" | grep -oP '(?<=Loaded image: ).*' || \
              echo "$LOADED" | grep -oP '(?<=Loaded image\(s\): ).*')

    if [ -n "$NEW_REF" ] && [ "$NEW_REF" != "{{ image_ref }}" ]; then
        echo "==> Retagging chunked image to {{ image_ref }}..."
        $SUDO_CMD podman tag "$NEW_REF" "{{ image_ref }}"
    fi

qcow2 variant flavor='base' repo='local':
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{ flavor }}" != "base" ]; then
        FLAVOR="-{{ flavor }}"
    else
        FLAVOR=
    fi
    if [ "{{ repo }}" = "ghcr" ]; then bash ./scripts/build-bootc-diskimage.sh qcow2 ghcr.io/{{ repo_organization }}/{{ variant }}$FLAVOR:{{ default_tag }}
    elif [ "{{ repo }}" = "local" ]; then bash ./scripts/build-bootc-diskimage.sh qcow2 localhost/{{ variant }}$FLAVOR:{{ default_tag }}
    else echo "DEBUG: repo '{{ repo }}' did not match ghcr or local"; exit 1
    fi

test-vm variant flavor='base':
    #!/usr/bin/env bash
    set -euo pipefail
    bash ./scripts/test-vm.sh {{ variant }} {{ flavor }}

debug-vm variant flavor='base' repo='local':
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{ repo }}" == "local" ]; then
        {{ just }} build {{ variant }} {{ flavor }}
    fi
    {{ just }} qcow2 {{ variant }} {{ flavor }} {{ repo }}
    {{ just }} test-vm {{ variant }} {{ flavor }}

iso variant flavor='base' repo='local' hook_script='iso_files/configure_lts_iso_anaconda.sh' flatpaks_file='system_files/etc/ublue-os/system-flatpaks.list':
    #!/usr/bin/env bash
    bash ./scripts/build-titanoboa.sh {{ variant }} {{ flavor }} {{ repo }} {{ hook_script }}
