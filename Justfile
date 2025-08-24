# --- Environment Variables & Exports ---

export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export default_tag := env("DEFAULT_TAG", "latest")
export bib_image := env("BIB_IMAGE", "quay.io/centos-bootc/bootc-image-builder:latest")
just := just_executable()

# --- Default Base Image (for 'regular' flavor builds) ---

export base_image := env("BASE_IMAGE", "quay.io/almalinuxorg/almalinux-bootc")
export base_image_tag := env("BASE_IMAGE_TAG", "10")

[private]
default:
    @{{ just }} --list

# Check Just Syntax
check:
    #!/usr/bin/env bash
    echo "Checking syntax of shell scripts..."
    /usr/bin/find . -iname "*.sh" -type f -exec shellcheck "{}" ";"
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

# ==============================================================================
#  BUILD PIPELINE
# ==============================================================================

# Private build engine. Now accepts final image name and brand as parameters.
[private]
_build target_tag_with_version target_tag container_file base_image_for_build platform='linux/amd64' use_cache="0" *args:
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
build variant='albacore' flavor='regular' platform='linux/amd64' is_ci="0" tag='latest' *args:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==============================================================="
    echo "Build config:"
    echo "  Variant: {{ variant }}"
    echo "  Flavor: {{ flavor }}"
    echo "  Platform: {{ platform }}"
    echo "  Is CI: {{ is_ci }}"
    echo "  Tag: {{ tag }}"
    echo "  Args: {{ args }}"
    echo "==============================================================="



    BASE_FOR_BUILD=""
    CONTAINERFILE="Containerfile"

    case "{{ flavor }}" in
        "regular")
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
            just build {{ variant }} regular
            just build {{ variant }} dx
            just build {{ variant }} gdx
            exit 0
            ;;
        *)
            echo "Unknown flavor '{{ flavor }}'. Valid options are: regular, dx, gdx, all."
            exit 1
            ;;
    esac

    TARGET_TAG={{ variant }}
    if [[ "{{ flavor }}" != "regular" ]]; then
        TARGET_TAG+="-{{ flavor }}"
    fi
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:{{ tag }}"

    echo "================================================================"
    echo "Building image with the following parameters:"
    echo "  Target Tag: ${TARGET_TAG_WITH_VERSION}"
    echo "  Variant: {{ variant }}"
    echo "  Containerfile: ${CONTAINERFILE}"
    echo "  Base Image for Build: ${BASE_FOR_BUILD}"
    echo "  Platform: {{ platform }}"
    echo "  is_ci: {{ is_ci }}"
    echo "  Additional Args: {{ args }}"
    echo "================================================================"

    if [[ "{{ is_ci }}" == "0" ]]; then
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "{{ platform }}" "1" {{ args }}
    else
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "{{ platform }}" "0" {{ args }}
    fi

# --- Build-all helpers ---
build-all-regular:
    just build yellowfin
    just build albacore
    just build skipjack
    just build bonito

build-all:
    just build yellowfin all
    just build albacore all
    just build skipjack all
    just build bonito all

lint:
    /usr/bin/find . -iname "*.sh" -type f -exec shellcheck "{}" ";"
