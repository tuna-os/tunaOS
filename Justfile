# --- Environment Variables & Exports ---

export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export default_tag := env("DEFAULT_TAG", "latest")
export bib_image := env("BIB_IMAGE", "quay.io/centos-bootc/bootc-image-builder:latest")
just := just_executable()
arch := arch()
export platform := if arch == "x86_64" { "linux/amd64" } else { if arch == "arm64" { "linux/arm64" } else { if arch == "aarch64" { "linux/arm64" } else { error("Unsupported ARCH '" + arch + "'. Supported values are 'x86_64', 'aarch64', and 'arm64'.") } } }

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
    /usr/bin/find . -iname "*.sh" -type f -exec shellcheck --exclude=SC1091 "{}" ";"
    find . -type f -name "*.yaml" | while read -r file; do
        echo "Checking syntax: $file"
        yamllint -c ./.yamllint.yml "$file" || { exit 1; }
    done
    find . -type f -name "*.yml" | while read -r file; do
        echo "Checking syntax: $file"
        yamllint "$file" || { exit 1; }
    done
    find . -type f -name "*.json" | while read -r file; do
        echo "Checking syntax: $file"
        jq . "$file" > /dev/null || { exit 1; }
    done
    find . -type f -name "*.just" | while read -r file; do
        echo "Checking syntax: $file"
        just --unstable --fmt --check -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt --check -f Justfile

# Fix Just Syntax
fix:
    #!/usr/bin/env bash
    echo "Fixing syntax of shell scripts..."
        /usr/bin/find . -iname "*.sh" -type f -exec shfmt --write "{}" ";"
    find . -type f -name "*.just" | while read -r file; do
        echo "Checking syntax: $file"
        just --unstable --fmt -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt -f Justfile || { exit 1; }

clean:
    #!/usr/bin/env bash
    echo "Cleaning up..."
    rm -rf '.rpm-cache-*'
    rm -rf .build-logs
    sudo rm -rf .build/*
    echo "Removing local podman images for all variants and flavors..."
    variants=(yellowfin albacore bonito skipjack)
    images=()
    for variant in "${variants[@]}"; do
        images+=("$variant")
        images+=("${variant}-dx")
        images+=("${variant}-gdx")
    done
    for img in "${images[@]}"; do
        podman rmi -f "localhost/${img}:latest" 2>/dev/null || true
    done
    for img in "${images[@]}"; do
        sudo podman rmi -f "localhost/${img}:latest" 2>/dev/null || true
    done

# ==============================================================================
#  BUILD PIPELINE
# ==============================================================================

# Private build engine. Now accepts final image name and brand as parameters.
[private]
_build target_tag_with_version target_tag container_file base_image_for_build platform use_cache *args:
    #!/usr/bin/env bash
    set -euxo pipefail

    BUILD_ARGS=()
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME={{ target_tag }}")
    BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR={{ repo_organization }}")
    BUILD_ARGS+=("--build-arg" "BASE_IMAGE={{ base_image_for_build }}")
    if [[ -z "$(git status -s)" ]]; then
        BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
    fi
    echo "{{ use_cache }}"
    if [[ "{{ use_cache }}" == "1" ]]; then
        mkdir -p "$(pwd)/.rpm-cache-{{ target_tag }}"
        BUILD_ARGS+=("--volume" "$(pwd)/.rpm-cache-{{ target_tag }}:/var/cache/dnf")
    fi

    podman build \
        --platform "{{ platform }}" \
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
# Example: just build yellowfin dx
#
# Usage (CI): just build image_name=<final_name> variant=<base_os> is_ci=true [flavor]

# Example: just build image_name=albacore variant=almalinux is_ci=true gdx
build variant='albacore' flavor='base' platform=`echo $platform` is_ci="0" tag='latest':
    #!/usr/bin/env bash
    set -euo pipefail

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
    echo -e "${BLUE}===============================================================${NC}"


    BASE_FOR_BUILD=""
    CONTAINERFILE="Containerfile"

    case "{{ flavor }}" in
        "base")
            BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
            ;;
        "dx")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.dx"
            ;;
        "gdx")
            if [[ "{{ is_ci }}" = "1" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}-dx:{{ tag }}"
            else
                BASE_FOR_BUILD="localhost/{{ variant }}-dx:{{ tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            ;;
        "all")
            just build {{ variant }} base
            just build {{ variant }} dx
            just build {{ variant }} gdx
            exit 0
            ;;
        *)
            echo "Unknown flavor '{{ flavor }}'. Valid options are: base, dx, gdx, all."
            exit 1
            ;;
    esac

    TARGET_TAG={{ variant }}
    if [[ "{{ flavor }}" != "base" ]]; then
        TARGET_TAG+="-{{ flavor }}"
    fi
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:{{ tag }}"

    echo -e "${BLUE}================================================================${NC}"
    echo -e "${GREEN}Building image with the following parameters:${NC}"
    echo -e "  Target Tag: ${YELLOW}${TARGET_TAG_WITH_VERSION}${NC}"
    echo -e "  Variant: ${YELLOW}{{ variant }}${NC}"
    echo -e "  Containerfile: ${YELLOW}${CONTAINERFILE}${NC}"
    echo -e "  Base Image for Build: ${YELLOW}${BASE_FOR_BUILD}${NC}"
    echo -e "  Platform: ${YELLOW}{{ platform }}${NC}"
    echo -e "  is_ci: ${YELLOW}{{ is_ci }}${NC}"
    echo -e "${BLUE}================================================================${NC}"

    if [[ "{{ is_ci }}" == "0" ]]; then
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "{{ platform }}" "1"
    else
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "{{ platform }}" "0"
    fi

yellowfin variant='base':
    just build yellowfin {{ variant }}

albacore variant='base':
    just build albacore {{ variant }}

skipjack variant='base':
    just build skipjack {{ variant }}

bonito variant='base':
    just build bonito {{ variant }}

build-all-base:
    #!/usr/bin/env bash
    set -euo pipefail
    bash ./scripts/build-all-images.sh --base-only --include-experimental

build-all:
    #!/usr/bin/env bash
    bash ./scripts/build-all-images.sh

build-all-experimental:
    #!/usr/bin/env bash
    bash ./scripts/build-all-images.sh --include-experimental

qcow2 variant flavor='base' repo='local':
    #!/usr/bin/env bash
    if [ "{{ flavor }}" != "base" ]; then
        FLAVOR="-{{ flavor }}"
    else
        FLAVOR=
    fi
    if [ "{{ repo }}" = "ghcr" ]; then bash ./scripts/build-bootc-diskimage.sh qcow2 ghcr.io/{{ repo_organization }}/{{ variant }}$FLAVOR:{{ default_tag }}
    elif [ "{{ repo }}" = "local" ]; then bash ./scripts/build-bootc-diskimage.sh qcow2 localhost/{{ variant }}$FLAVOR:{{ default_tag }}
    fi

iso variant flavor='base' repo='local' hook_script='iso_files/configure_lts_iso_anaconda.sh' flatpaks_file='system_files/etc/ublue-os/system-flatpaks.list':
    #!/usr/bin/env bash
    bash ./scripts/build-titanoboa.sh {{ variant }} {{ flavor }} {{ repo }} {{ hook_script }}
