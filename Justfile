# --- Environment Variables & Exports ---

export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export image_name := env("IMAGE_NAME", "albacore")
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
    /usr/bin/find . -iname "*.sh" -type f -exec shellcheck "{}" ';'
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
        /usr/bin/find . -iname "*.sh" -type f -exec shfmt --write "{}" ';'
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
_build target_tag final_image_name container_file base_image_for_build platform='linux/amd64' *args:
    #!/usr/bin/env bash
    set -euxo pipefail

    BUILD_ARGS=()
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME={{ final_image_name }}")
    BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR={{ repo_organization }}")
    BUILD_ARGS+=("--build-arg" "BASE_IMAGE={{ base_image_for_build }}")
    if [[ -z "$(git status -s)" ]]; then
        BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
    fi

    podman build \
        --platform "{{ platform }}" \
        "${BUILD_ARGS[@]}" \
        {{ args }} \
        --pull=newer \
        --tag "{{ target_tag }}" \
        --file "{{ container_file }}" \
        .

# --- Unified Build Pipeline ---
# This rule now handles both local and CI builds.
# For CI builds, pass `is_ci=true` and `image_name` as the final tag.
# For local builds, pass `is_ci=false` (or omit) and `variant` as the local name.
#
# Usage (local): just build <variant> [flavor]
# Example: just build yellowfin dx
#
# Usage (CI): just build image_name=<final_name> variant=<base_os> is_ci=true [flavor]

# Example: just build image_name=albacore variant=almalinux is_ci=true gdx
build variant='albacore' flavor='regular' platform='linux/amd64' is_ci="false" image_name='albacore' *args:
    #!/usr/bin/env bash
    set -euo pipefail

    TARGET_TAG="{{ image_name }}"
    [[ "{{ flavor }}" != "regular" ]] && TARGET_TAG="{{ image_name }}-{{ flavor }}"
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:{{ default_tag }}"

    if [[ "{{ is_ci }}" = "true" ]]; then
        local_image_name="{{ image_name }}"
    else
        local_image_name="{{ variant }}"
    fi

    BASE_FOR_BUILD=""
    CONTAINERFILE="Containerfile"

    case "{{ flavor }}" in
        "regular")
            case "{{ variant }}" in
                "yellowfin"|"almalinux-kitten") BASE_FOR_BUILD="quay.io/almalinuxorg/almalinux-bootc:10-kitten" ;;
                "albacore"|"almalinux")        BASE_FOR_BUILD="quay.io/almalinuxorg/almalinux-bootc:10" ;;
                "skipjack"|"centos"|"lts")     BASE_FOR_BUILD="quay.io/centos-bootc/centos-bootc:stream10" ;;
                "bonito"|"fedora"|"bluefin")   BASE_FOR_BUILD="quay.io/fedora/fedora-bootc:42" ;;
                "bonito-rawhide"|"rawhide")    BASE_FOR_BUILD="quay.io/fedora/fedora-bootc:rawhide" ;;
            esac
            ;;
        "dx")
            if [[ "{{ is_ci }}" = "true" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ image_name }}:{{ default_tag }}"
            else
                BASE_FOR_BUILD="localhost/${local_image_name}:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.dx"
            ;;
        "gdx")
            if [[ "{{ is_ci }}" = "true" ]]; then
                BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ image_name }}-dx:{{ default_tag }}"
            else
                BASE_FOR_BUILD="localhost/${local_image_name}-dx:{{ default_tag }}"
            fi
            CONTAINERFILE="Containerfile.gdx"
            ;;
        "all")
            just build variant={{ variant }} image_name={{ image_name }} is_ci={{ is_ci }} regular
            just build variant={{ variant }} image_name={{ image_name }} is_ci={{ is_ci }} dx
            just build variant={{ variant }} image_name={{ image_name }} is_ci={{ is_ci }} gdx
            exit 0
            ;;
        *)
            echo "Unknown flavor '{{ flavor }}'. Valid options are: regular, dx, gdx, all."
            exit 1
            ;;
    esac

    final_image_name="{{ image_name }}"
    if [[ "{{ is_ci }}" = "false" ]]; then
        final_image_name="${local_image_name}"
    fi

    just _build "${TARGET_TAG_WITH_VERSION}" "${final_image_name}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "{{ platform }}" {{ args }}

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
    /usr/bin/find . -iname "*.sh" -type f -exec shellcheck "{}" ';'

# Runs shfmt on all Bash scripts
format:
