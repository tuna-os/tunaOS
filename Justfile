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
    if command -v actionlint &> /dev/null; then
        echo "Checking syntax of GitHub Actions workflows..."
        # Ignore id-token: write permission warnings which are false positives for OIDC
        # Ignore various shellcheck warnings that are often intentional or problematic in YAML
        # Ignore deprecated save-always in actions/cache as it's common in these workflows
        actionlint -ignore "permission \"id-token\" is unknown" \
                   -ignore "SC2086" -ignore "SC2129" -ignore "SC2001" \
                   -ignore "SC2034" -ignore "SC2015" -ignore "SC1001" \
                   -ignore "SC2295" \
                   -ignore "save-always" \
                   .github/workflows/*.yml .github/workflows/*.yaml || { exit 1; }
    fi
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
    if [[ "{{ is_ci }}" != "1" ]]; then
        git submodule update --init --recursive
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
    if LOADED=$($SUDO_CMD podman run --rm \
        --security-opt label=disable \
        --mount=type=image,src="{{ image_ref }}",target=/chunkah \
        -e "CHUNKAH_CONFIG_STR=$CONFIG" \
        quay.io/jlebon/chunkah:latest build | $SUDO_CMD podman load); then

        echo "$LOADED"

        # Parse the loaded image reference
        NEW_REF=$(echo "$LOADED" | grep -oP '(?<=Loaded image: ).*' || \
                  echo "$LOADED" | grep -oP '(?<=Loaded image\(s\): ).*')

        if [ -n "$NEW_REF" ] && [ "$NEW_REF" != "{{ image_ref }}" ]; then
            echo "==> Retagging chunked image to {{ image_ref }}..."
            $SUDO_CMD podman tag "$NEW_REF" "{{ image_ref }}"
        fi
    else
        echo "==> WARNING: Chunkify failed (non-fatal), skipping layer optimization."
    fi

# Run the full staged build pipeline locally, mirroring the CI job graph.
# Reads .github/build-config.yml for the variant/flavor/stage structure.
# Builds within each stage run in parallel; stages are sequential.
#
# Requires zellij for the live UI (overview pane + one log pane per build).
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
#   tag=<tag>   image tag (default: latest)
pipeline variant='all' flavor='all' tag='latest' dry_run='0':
    #!/usr/bin/env bash
    set -euo pipefail

    FILTER_VARIANT="{{ variant }}"
    FILTER_FLAVOR="{{ flavor }}"
    TAG="{{ tag }}"
    DRY_RUN="{{ dry_run }}"
    JUST="{{ just }}"
    LOG_DIR=".build-logs"
    mkdir -p "$LOG_DIR"

    # ── Helpers ──────────────────────────────────────────────────────────────

    local_ref() { echo "localhost/${1}:${2}"; }

    parent_for() {
        case "$1" in
            *-gdx-hwe) echo "base-hwe" ;;
            *-gdx)     echo "base-gdx" ;;
            *-hwe)     echo "base-hwe" ;;
            *)         echo ""         ;;
        esac
    }

    stage1_base_ref() { echo ""; }
    stage2_base_ref() { local_ref "$1" "base"; }
    stage3_base_ref() {
        local parent; parent=$(parent_for "$2")
        if [[ -n "$parent" ]]; then local_ref "$1" "$parent"
        else echo "WARNING: no parent for stage-3 flavor '$2'" >&2; echo ""; fi
    }

    # ── Zellij detection ─────────────────────────────────────────────────────

    USE_ZELLIJ=0
    if command -v zellij &>/dev/null && [[ -z "${ZELLIJ:-}" ]] && [[ "$DRY_RUN" != "1" ]]; then
        USE_ZELLIJ=1
    fi

    # ── Overview pane script ──────────────────────────────────────────────────
    # Written to a temp file and run inside the zellij overview pane.
    # Reads a shared status dir where each job writes:
    #   $STATUS_DIR/{variant}-{flavor}  →  "running\t<start_epoch>"
    #                                   →  "done\t<start_epoch>\t<end_epoch>"
    #                                   →  "failed\t<start_epoch>\t<end_epoch>"
    # The script re-renders the board every second until all jobs are terminal.

    write_overview_script() {
        local script_file=$1
        local status_dir=$2
        local stage_name=$3
        local total_stages=$4
        local current_stage=$5
        shift 5
        local labels=("$@")   # ordered list of "variant:flavor" labels

        cat > "$script_file" << 'OVERVIEW_EOF'
#!/usr/bin/env bash
STATUS_DIR="__STATUS_DIR__"
STAGE_NAME="__STAGE_NAME__"
CURRENT_STAGE=__CURRENT_STAGE__
TOTAL_STAGES=__TOTAL_STAGES__
LABELS=(__LABELS__)

SPINNER_FRAMES=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
spin_idx=0

# ANSI
BOLD="\033[1m"
DIM="\033[2m"
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
CYAN="\033[36m"
RESET="\033[0m"
CLEAR_SCREEN="\033[2J\033[H"

fmt_duration() {
    local secs=$1
    printf "%d:%02d" $((secs / 60)) $((secs % 60))
}

render() {
    local now; now=$(date +%s)
    local spin="${SPINNER_FRAMES[$((spin_idx % ${#SPINNER_FRAMES[@]}))]}"
    local all_done=1

    printf "%b" "$CLEAR_SCREEN"
    printf "%b" "${BOLD}  TunaOS Build Pipeline${RESET}\n"
    printf "  Stage %d / %d  —  %s\n\n" "$CURRENT_STAGE" "$TOTAL_STAGES" "$STAGE_NAME"

    # Header row
    printf "  ${BOLD}%-30s  %-10s  %s${RESET}\n" "IMAGE" "STATUS" "TIME"
    printf "  %s\n" "$(printf '─%.0s' {1..52})"

    for label in "${LABELS[@]}"; do
        local key="${label//:/-}"
        local state_file="$STATUS_DIR/$key"
        if [[ ! -f "$state_file" ]]; then
            printf "  %-30s  ${DIM}%-10s${RESET}  %s\n" "$label" "waiting" "--:--"
            all_done=0
            continue
        fi
        IFS=$'\t' read -r state start_epoch rest < "$state_file" || true
        local elapsed=$(( now - start_epoch ))
        case "$state" in
            running)
                printf "  %-30s  ${YELLOW}%s %-8s${RESET}  %s\n" \
                    "$label" "$spin" "building" "$(fmt_duration $elapsed)"
                all_done=0
                ;;
            done)
                IFS=$'\t' read -r _s _start end_epoch <<< "$(cat "$state_file")"
                local took=$(( end_epoch - start_epoch ))
                printf "  %-30s  ${GREEN}✓ %-8s${RESET}  %s\n" \
                    "$label" "done" "$(fmt_duration $took)"
                ;;
            failed)
                IFS=$'\t' read -r _s _start end_epoch <<< "$(cat "$state_file")"
                local took=$(( end_epoch - start_epoch ))
                printf "  %-30s  ${RED}✗ %-8s${RESET}  %s\n" \
                    "$label" "FAILED" "$(fmt_duration $took)"
                ;;
        esac
    done

    printf "\n  ${DIM}Logs: .build-logs/   │   %s${RESET}\n" "$(date '+%H:%M:%S')"

    if [[ "$all_done" == "1" ]]; then
        printf "\n  ${BOLD}${GREEN}All jobs complete.${RESET}\n"
        exit 0
    fi
}

while true; do
    render
    spin_idx=$(( spin_idx + 1 ))
    sleep 0.8
done
OVERVIEW_EOF

        # Substitute placeholders
        local labels_str=""
        for l in "${labels[@]}"; do labels_str+="\"$l\" "; done
        sed -i \
            -e "s|__STATUS_DIR__|${status_dir}|g" \
            -e "s|__STAGE_NAME__|${stage_name}|g" \
            -e "s|__CURRENT_STAGE__|${current_stage}|g" \
            -e "s|__TOTAL_STAGES__|${total_stages}|g" \
            -e "s|__LABELS__|${labels_str}|g" \
            "$script_file"
        chmod +x "$script_file"
    }

    # ── KDL layout builder ────────────────────────────────────────────────────
    # Generates a layout with the overview pane on the left (fixed width) and
    # one log-tail pane per build stacked vertically on the right.

    write_zellij_layout() {
        local layout_file=$1
        local overview_script=$2
        shift 2
        local panes=("$@")   # alternating: logfile label ...

        {
            echo 'layout {'
            # Root split: overview left (40 cols) | logs right
            echo '  pane split_direction="horizontal" {'

            # Overview pane — fixed width, runs the status board script
            printf '    pane size=40 name="Overview" {\n'
            printf '      command "%s"\n' "$overview_script"
            printf '    }\n'

            # Right column: all log panes stacked vertically
            echo '    pane split_direction="vertical" {'
            local i=0
            while [[ $i -lt ${#panes[@]} ]]; do
                local logfile="${panes[$i]}"
                local label="${panes[$((i+1))]}"
                printf '      pane name="%s" {\n' "$label"
                printf '        command "tail"\n'
                printf '        args "-n" "50" "-f" "%s"\n' "$logfile"
                printf '      }\n'
                i=$((i + 2))
            done
            echo '    }'
            echo '  }'
            echo '}'
        } > "$layout_file"
    }

    # ── Parallel stage runner ─────────────────────────────────────────────────

    TOTAL_STAGES=3
    CURRENT_STAGE=0

    run_stage() {
        local stage_name=$1
        local entries=$2
        local base_ref_fn=$3
        CURRENT_STAGE=$(( CURRENT_STAGE + 1 ))

        if [[ -z "$entries" ]]; then return 0; fi

        # ── Collect job metadata ──────────────────────────────────────────
        local -a vs=() fs=() logfiles=() base_refs=() labels=() pane_args=()
        local status_dir; status_dir=$(mktemp -d /tmp/pipeline-status-XXXXXX)

        while IFS=$'\t' read -r v f _s; do
            local base_ref; base_ref=$("$base_ref_fn" "$v" "$f")
            local logfile="${LOG_DIR}/${v}-${f}.log"
            : > "$logfile"
            vs+=("$v"); fs+=("$f")
            logfiles+=("$logfile")
            base_refs+=("$base_ref")
            labels+=("${v}:${f}")
            pane_args+=("$logfile" "${v}:${f}")
        done <<< "$entries"

        local count=${#vs[@]}

        echo ""
        echo "╔══════════════════════════════════════════════════════════════╗"
        printf "║  Stage %d/%d — %-51s║\n" "$CURRENT_STAGE" "$TOTAL_STAGES" "$stage_name"
        echo "╚══════════════════════════════════════════════════════════════╝"
        echo "  Launching $count build(s) in parallel..."

        # ── Write zellij layout & overview script ─────────────────────────
        local layout_file overview_script zellij_session=""
        layout_file=$(mktemp /tmp/zellij-layout-XXXXXX.kdl)
        overview_script=$(mktemp /tmp/pipeline-overview-XXXXXX.sh)

        if [[ "$USE_ZELLIJ" == "1" ]]; then
            write_overview_script \
                "$overview_script" "$status_dir" \
                "$stage_name" "$TOTAL_STAGES" "$CURRENT_STAGE" \
                "${labels[@]}"
            write_zellij_layout "$layout_file" "$overview_script" "${pane_args[@]}"
            zellij_session="pipeline-$$-${CURRENT_STAGE}"
            zellij --session "$zellij_session" --layout "$layout_file" &
            echo "  zellij session '$zellij_session' — attach: zellij attach $zellij_session"
        fi

        # ── Launch builds ─────────────────────────────────────────────────
        local -a pids=()
        for (( i=0; i<count; i++ )); do
            local v="${vs[$i]}" f="${fs[$i]}"
            local logfile="${logfiles[$i]}" base_ref="${base_refs[$i]}"
            local key="${v}-${f}"

            if [[ "$DRY_RUN" == "1" ]]; then
                echo "[dry-run] build $v $f (base: ${base_ref:-none})"
                pids+=(-1)
                continue
            fi

            # Write status file and run build, updating status on exit
            (
                local start; start=$(date +%s)
                printf "%s\t%s" "running" "$start" > "$status_dir/$key"
                if [[ "$USE_ZELLIJ" == "1" ]]; then
                    "$JUST" build "$v" "$f" "" "0" "$TAG" "$base_ref" \
                        >"$logfile" 2>&1
                else
                    "$JUST" build "$v" "$f" "" "0" "$TAG" "$base_ref" \
                        > >(while IFS= read -r line; do
                                printf "[%s:%s] %s\n" "$v" "$f" "$line"
                            done | tee -a "$logfile") 2>&1
                fi
                local end; end=$(date +%s)
                printf "%s\t%s\t%s" "done" "$start" "$end" > "$status_dir/$key"
            ) &
            pids+=($!)
            echo "  ↳ ${v}:${f}  pid=$!  log=${logfile}"
        done

        echo ""

        # ── Wait & report ─────────────────────────────────────────────────
        local any_failed=0
        for (( i=0; i<count; i++ )); do
            local pid="${pids[$i]}"
            [[ "$pid" == "-1" ]] && continue
            local code=0
            wait "$pid" || code=$?
            local v="${vs[$i]}" f="${fs[$i]}" key="${vs[$i]}-${fs[$i]}"
            if [[ $code -ne 0 ]]; then
                # Overwrite status as failed (subshell may not have reached its trap)
                local start; start=$(awk -F'\t' '{print $2}' "$status_dir/$key" 2>/dev/null || date +%s)
                printf "%s\t%s\t%s" "failed" "$start" "$(date +%s)" > "$status_dir/$key"
                echo "  ✗  ${v}:${f}  (exit $code — see ${logfiles[$i]})"
                any_failed=1
            else
                echo "  ✓  ${v}:${f}"
            fi
        done

        # ── Teardown zellij ───────────────────────────────────────────────
        if [[ "$USE_ZELLIJ" == "1" ]] && [[ -n "$zellij_session" ]]; then
            sleep 2   # let overview render the final state
            zellij delete-session "$zellij_session" --force 2>/dev/null || true
        fi
        rm -f "$layout_file" "$overview_script"
        rm -rf "$status_dir"

        if [[ $any_failed -ne 0 ]]; then
            echo ""
            echo "✗  Stage '$stage_name' failed. Aborting pipeline."
            echo "   Logs: $LOG_DIR/"
            return 1
        fi
        echo "  ✓  Stage complete."
    }

    # ── Load config & filter ─────────────────────────────────────────────────

    ENTRIES=$(yq -o=json '.' .github/build-config.yml | jq -r '
        .variants[]
        | . as $v
        | .flavors[]
        | select(
            ("'"$FILTER_VARIANT"'" == "all" or $v.id == "'"$FILTER_VARIANT"'") and
            ("'"$FILTER_FLAVOR"'" == "all" or .id == "'"$FILTER_FLAVOR"'")
          )
        | [$v.id, .id, (.stage | tostring)] | join("\t")
    ')

    if [[ -z "$ENTRIES" ]]; then
        echo "No entries for variant='$FILTER_VARIANT' flavor='$FILTER_FLAVOR'."
        exit 1
    fi

    STAGE1=$(echo "$ENTRIES" | awk -F'\t' '$3 == "1"' || true)
    STAGE2=$(echo "$ENTRIES" | awk -F'\t' '$3 == "2"' || true)
    STAGE3=$(echo "$ENTRIES" | awk -F'\t' '$3 == "3"' || true)

    count_lines() { [[ -z "${1:-}" ]] && echo 0 || echo "$1" | wc -l | tr -d ' '; }
    total=$(echo "$ENTRIES" | wc -l | tr -d ' ')

    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  TunaOS Pipeline                                             ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo "  Images : $total  ($(count_lines "$STAGE1") + $(count_lines "$STAGE2") + $(count_lines "$STAGE3") across 3 stages)"
    echo "  Filter : variant=${FILTER_VARIANT}  flavor=${FILTER_FLAVOR}  tag=${TAG}"
    if [[ "$USE_ZELLIJ" == "1" ]]; then
        echo "  UI     : zellij  (overview + per-build log panes)"
    else
        echo "  UI     : inline  (install zellij for live panes)"
    fi
    [[ "$DRY_RUN" == "1" ]] && echo "  Mode   : DRY RUN"
    echo ""

    run_stage "base images"                   "$STAGE1" stage1_base_ref
    run_stage "base-hwe / base-gdx / desktop" "$STAGE2" stage2_base_ref
    run_stage "HWE / GDX desktop flavors"     "$STAGE3" stage3_base_ref

    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  Pipeline complete ✓                                         ║"
    echo "╚══════════════════════════════════════════════════════════════╝"

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

test-vm variant flavor='gnome':
    #!/usr/bin/env bash
    set -euo pipefail
    bash ./scripts/test-vm.sh {{ variant }} {{ flavor }}

iso variant flavor='gnome' repo='local' hook_script='iso_files/configure_lts_iso_anaconda.sh' flatpaks_file='system_files/etc/ublue-os/system-flatpaks.list':
    #!/usr/bin/env bash
    bash ./scripts/build-titanoboa.sh {{ variant }} {{ flavor }} {{ repo }} {{ hook_script }}
