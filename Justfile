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

_ensure_check_deps:
    #!/usr/bin/env bash
    if ! command -v shellcheck &> /dev/null; then
        brew install shellcheck
    fi
    if ! command -v shfmt &> /dev/null; then
        brew install shfmt
    fi
    if ! command -v yamllint &> /dev/null; then
        brew install yamllint
    fi
    if ! command -v jq &> /dev/null; then
        brew install jq
    fi
    if ! command -v actionlint &> /dev/null; then
        brew install actionlint
    fi

# Check Just Syntax
check: _ensure_check_deps
    #!/usr/bin/env bash
    echo "Checking syntax of shell scripts..."
    /usr/bin/find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -iname "*.sh" -type f -exec shellcheck --exclude=SC1091 "{}" ";"
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.yaml" | while read -r file; do
        yamllint -c ./.yamllint.yml "$file" || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.yml" | while read -r file; do
        yamllint "$file" || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.json" | while read -r file; do
        jq . "$file" > /dev/null || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.just" | while read -r file; do
        just --unstable --fmt --check -f $file
    done
    if command -v actionlint &> /dev/null; then
        actionlint -ignore "permission \"id-token\" is unknown" \
                   -ignore "SC2086" -ignore "SC2129" -ignore "SC2001" \
                   -ignore "SC2034" -ignore "SC2015" -ignore "SC1001" \
                   -ignore "SC2295" \
                   -ignore "save-always" \
                   -ignore "cannot be filtered" \
                   .github/workflows/*.yml .github/workflows/*.yaml || { exit 1; }
    fi
    just --unstable --fmt --check -f Justfile

# Fix Just Syntax
fix:
    #!/usr/bin/env bash
    echo "Fixing syntax of shell scripts..."
        /usr/bin/find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -iname "*.sh" -type f -exec shfmt --write "{}" ";"
    find . -type f -name "*.just" | while read -r file; do
        just --unstable --fmt -f $file
    done
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

# NVIDIA drivers and the coreos/fedora kernel.
[private]
_build target_tag_with_version target_tag container_file base_image_for_build target_platform use_cache enable_gdx enable_hwe desktop_flavor *args: _ensure-yq
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

    BUILD_ARGS+=("--build-arg" "AKMODS_BASE=ghcr.io/ublue-os")

    # Pass RHSM credentials for RHEL registration during build
    BUILD_ARGS+=("--build-arg" "RHSM_USER=${RHSM_USER:-}")
    BUILD_ARGS+=("--build-arg" "RHSM_PASSWORD=${RHSM_PASSWORD:-}")
    BUILD_ARGS+=("--build-arg" "RHSM_ORG=${RHSM_ORG:-}")
    BUILD_ARGS+=("--build-arg" "RHSM_ACTIVATION_KEY=${RHSM_ACTIVATION_KEY:-}")

    # Select akmods source tag for mounted NVIDIA images.
    # HWE and bonito (Fedora) always use coreos-stable.
    if [[ "{{ enable_hwe }}" -eq "1" ]] || [[ "{{ target_tag }}" == bonito* ]]; then
        BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=coreos-stable-{{ coreos_stable_version }}")
        BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=coreos-stable-{{ coreos_stable_version }}")
    else
        BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=centos-10")
        BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=centos-10")
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
    elif [[ "{{ desktop_flavor }}" == "hwe-base" ]] || [[ "{{ desktop_flavor }}" == "hwe-base-node" ]]; then
        BUILD_TARGET="hwe-base"
    elif [[ "{{ desktop_flavor }}" == "gdx-base" ]] || [[ "{{ desktop_flavor }}" == "gdx-base-node" ]]; then
        BUILD_TARGET="gdx-base"
    fi

    podman build \
        --dns=8.8.8.8 \
        --platform "{{ target_platform }}" \
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
build variant='albacore' flavor='gnome' target_platform='' is_ci="0" tag='latest' chain_base_image='':
    #!/usr/bin/env bash
    set -euo pipefail

    # Initialize submodules locally (CI uses actions/checkout with submodules: recursive)
    DID_INIT="0"
    if [[ "{{ is_ci }}" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]]; then
        git submodule update --init --recursive
        DID_INIT="1"
    fi

    # ANSI color codes
    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m' # No Color

    echo -e "${BLUE}===============================================================${NC}"
    # Fetch platforms from config if not provided
    if [[ -z "{{ target_platform }}" ]]; then
        # Default to native platform if not specified and not in CI
        if [[ "{{ is_ci }}" != "1" ]]; then
            PLATFORM="{{ platform }}"
        else
            # In CI, we expect a platform or we'd fetch all (but reusable workflow always passes one)
            PLATFORM=$(yq -r ".variants[] | select(.id == \"{{ variant }}\") | .platforms | join(\",\")" .github/build-config.yml)
        fi
    else
        PLATFORM="{{ target_platform }}"
    fi
    echo -e "${GREEN}Build config:${NC}"
    echo -e "  Variant: ${YELLOW}{{ variant }}${NC}"
    echo -e "  Flavor: ${YELLOW}{{ flavor }}${NC}"
    echo -e "  Platform: ${YELLOW}${PLATFORM}${NC}"
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
            DESKTOP_FLAVOR="base-no-de"
            ;;
        "gnome")
            BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
            ;;
        "hwe"|"gnome-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-gnome:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:gnome"
            fi
            CONTAINERFILE="Containerfile.hwe"
            ;;
        "gdx"|"gnome-gdx")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-gnome:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:gnome"
            fi
            CONTAINERFILE="Containerfile.gdx"
            ;;
        "gdx-hwe"|"gnome-gdx-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-gnome-hwe:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:gnome-hwe"
            fi
            CONTAINERFILE="Containerfile.gdx"
            ;;
        "hwe-base"|"hwe-base-node")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-gnome:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:gnome"
            fi
            CONTAINERFILE="Containerfile.hwe"
            DESKTOP_FLAVOR="hwe-base"
            ;;
        "gdx-base"|"gdx-base-node")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-gnome:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:gnome"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="gdx-base"
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
                BASE_FOR_BUILD="localhost/{{ variant }}:kde"
            fi
            CONTAINERFILE="Containerfile.hwe"
            DESKTOP_FLAVOR="kde"
            ;;
        "kde-gdx")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-kde:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:kde"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="kde"
            ;;
        "kde-gdx-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-kde-hwe:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:kde-hwe"
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
                BASE_FOR_BUILD="localhost/{{ variant }}:niri"
            fi
            CONTAINERFILE="Containerfile.hwe"
            DESKTOP_FLAVOR="niri"
            ;;
        "niri-gdx")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-niri:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:niri"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="niri"
            ;;
        "niri-gdx-hwe")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-niri-hwe:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:niri-hwe"
            fi
            CONTAINERFILE="Containerfile.gdx"
            DESKTOP_FLAVOR="niri"
            ;;
        "all")
            just build {{ variant }} base
            just build {{ variant }} gnome
            just build {{ variant }} gnome-hwe
            just build {{ variant }} gnome-gdx
            just build {{ variant }} hwe-base
            just build {{ variant }} gdx-base
            just build {{ variant }} gnome-gdx-hwe
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
            echo "Unknown flavor '{{ flavor }}'. Valid options are: base, gnome, gnome-hwe, gnome-gdx, hwe-base, gdx-base, gnome-gdx-hwe, kde, kde-hwe, kde-gdx, kde-gdx-hwe, niri, niri-hwe, niri-gdx, niri-gdx-hwe, all."
            exit 1
            ;;
    esac

    # Allow workflow callers to chain from an explicit parent image.
    if [[ -n "{{ chain_base_image }}" ]] && [[ "{{ flavor }}" != "base" ]]; then
        BASE_FOR_BUILD="{{ chain_base_image }}"
    fi

    TARGET_TAG={{ variant }}
    TARGET_IMAGE_TAG="{{ tag }}"
    if [[ "{{ tag }}" == "latest" ]]; then
        TARGET_IMAGE_TAG="{{ flavor }}"
    fi
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:${TARGET_IMAGE_TAG}"

    # Determine HWE flag - hwe and gdx flavors always use coreos akmods
    ENABLE_HWE="0"
    if [[ "{{ flavor }}" == "hwe" ]] || [[ "{{ flavor }}" == "gnome-hwe" ]] || [[ "{{ flavor }}" == "hwe-base" ]] || [[ "{{ flavor }}" == "hwe-base-node" ]] || [[ "{{ flavor }}" == "gdx-hwe" ]] || [[ "{{ flavor }}" == "gnome-gdx-hwe" ]] || [[ "{{ flavor }}" == "kde-hwe" ]] || [[ "{{ flavor }}" == "kde-gdx-hwe" ]] || [[ "{{ flavor }}" == "niri-hwe" ]] || [[ "{{ flavor }}" == "niri-gdx-hwe" ]]; then
        ENABLE_HWE="1"
    fi

    # Determine GDX flag
    ENABLE_GDX="0"
    if [[ "{{ flavor }}" == "gdx" ]] || [[ "{{ flavor }}" == "gnome-gdx" ]] || [[ "{{ flavor }}" == "gdx-base" ]] || [[ "{{ flavor }}" == "gdx-base-node" ]] || [[ "{{ flavor }}" == "kde-gdx" ]] || [[ "{{ flavor }}" == "gdx-hwe" ]] || [[ "{{ flavor }}" == "gnome-gdx-hwe" ]] || [[ "{{ flavor }}" == "kde-gdx-hwe" ]] || [[ "{{ flavor }}" == "niri-gdx" ]] || [[ "{{ flavor }}" == "niri-gdx-hwe" ]]; then
        ENABLE_GDX="1"
    fi

    echo -e "${BLUE}================================================================${NC}"
    echo -e "${GREEN}Building image with the following parameters:${NC}"
    echo -e "  Target Tag: ${YELLOW}${TARGET_TAG_WITH_VERSION}${NC}"
    echo -e "  Variant: ${YELLOW}{{ variant }}${NC}"
    echo -e "  Containerfile: ${YELLOW}${CONTAINERFILE}${NC}"
    echo -e "  Base Image for Build: ${YELLOW}${BASE_FOR_BUILD}${NC}"
    echo -e "  Platform: ${YELLOW}${PLATFORM}${NC}"
    echo -e "  is_ci: ${YELLOW}{{ is_ci }}${NC}"
    echo -e "  Desktop Flavor: ${YELLOW}${DESKTOP_FLAVOR}${NC}"
    echo -e "  Enable HWE (uses coreos akmods): ${YELLOW}${ENABLE_HWE}${NC}"
    echo -e "  Enable GDX: ${YELLOW}${ENABLE_GDX}${NC}"
    echo -e "${BLUE}================================================================${NC}"

    if [[ "{{ is_ci }}" == "0" ]]; then
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "$PLATFORM" "1" "${ENABLE_GDX}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}"
        # Chunkify the built image for optimal layer distribution
        {{ just }} chunkify "${TARGET_TAG_WITH_VERSION}"
        # Sync cache after successful local build for deduplication
        ./scripts/sync-build-cache.sh "${TARGET_TAG}" || true
    else
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "$PLATFORM" "0" "${ENABLE_GDX}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}"
    fi

    if [[ "$DID_INIT" == "1" ]]; then
        echo "De-initializing submodules..."
        git submodule deinit -f --all
    fi

# ── Chunkah ──────────────────────────────────────────────────────────

# Use the pre-built chunkah image from ghcr.io/tuna-os/chunkah, fallback to local build
chunkify image_ref:
    #!/usr/bin/env bash
    set -euo pipefail

    CHUNKAH_IMG="ghcr.io/tuna-os/chunkah:latest"
    if podman image exists localhost/chunkah:latest; then
        echo "==> Using local chunkah build (localhost/chunkah:latest)"
        CHUNKAH_IMG="localhost/chunkah:latest"
    fi

    echo "==> Chunkifying {{ image_ref }}..."

    # Get config from existing image
    CONFIG=$(podman inspect "{{ image_ref }}")

    # Run chunkah (default 64 layers) and pipe to podman load
    # Uses --mount=type=image to expose the source image content to chunkah
    # Note: We need --privileged for some podman-in-podman/mount scenarios or just standard access
    if LOADED=$(podman run --rm \
        --security-opt label=disable \
        --mount=type=image,src="{{ image_ref }}",target=/chunkah \
        -e "CHUNKAH_CONFIG_STR=$CONFIG" \
        "${CHUNKAH_IMG}" build | podman load); then

        echo "$LOADED"

        # Parse the loaded image reference
        NEW_REF=$(echo "$LOADED" | grep -oP '(?<=Loaded image: ).*' || \
                  echo "$LOADED" | grep -oP '(?<=Loaded image\(s\): ).*')

        if [ -n "$NEW_REF" ] && [ "$NEW_REF" != "{{ image_ref }}" ]; then
            echo "==> Retagging chunked image to {{ image_ref }}..."
            podman tag "$NEW_REF" "{{ image_ref }}"
        fi
    else
        echo "==> WARNING: Chunkify failed (non-fatal), skipping layer optimization."
    fi

# Build chunkah locally from the tuna-os fork
build-chunkah path="":
    ./scripts/build-chunkah.sh {{ path }}

# Run the full staged build pipeline locally, mirroring the CI job graph.
# Reads .github/build-config.yml for the variant/flavor/stage structure.
# Builds within each stage run in parallel; stages are sequential.
#
# Requires zellij for the live UI (overview status board + one log pane per build).
# Falls back to prefixed stdout if zellij is not available.
# Logs always written to .build-logs/{variant}-{flavor}.log.
#
# Usage:
#   just pipeline                    # build everything
#   just pipeline yellowfin          # one variant, all flavors
#   just pipeline yellowfin gnome    # one flavor (respects stage deps)
#   just pipeline all gnome-hwe      # one flavor across all variants
#
# Options:
#   dry_run=1   print commands without executing

# tag=<tag>   image tag (default: latest)
pipeline variant='all' flavor='all' tag='latest' dry_run='0':
    #!/usr/bin/env bash
    export JUST="{{ just }}"
    ./scripts/pipeline.sh "{{ variant }}" "{{ flavor }}" "{{ tag }}" "{{ dry_run }}"

qcow2 variant flavor='gnome' repo='local':
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

# Attach to the currently running Zellij pipeline session
attach:
    #!/usr/bin/env bash
    # First try pipeline- specific sessions
    SESSION=$(zellij list-sessions 2>/dev/null | grep "pipeline-" | head -1 | awk '{print $1}')
    if [ -z "$SESSION" ]; then
        # Fall back to any session that isn't a gemini- session
        SESSION=$(zellij list-sessions 2>/dev/null | grep -v "gemini-" | head -1 | awk '{print $1}')
    fi
    if [ -n "$SESSION" ]; then
        echo "Attaching to Zellij session: $SESSION"
        zellij attach "$SESSION"
    else
        echo "No active zellij session found."
        exit 1
    fi

test-vm variant flavor='gnome':
    #!/usr/bin/env bash
    set -euo pipefail
    bash ./scripts/test-vm.sh {{ variant }} {{ flavor }}

iso variant flavor='gnome' repo='local' hook_script='iso_files/configure_lts_iso_anaconda.sh' flatpaks_file='system_files/etc/ublue-os/system-flatpaks.list':
    #!/usr/bin/env bash
    bash ./scripts/build-titanoboa.sh {{ variant }} {{ flavor }} {{ repo }} {{ hook_script }}
