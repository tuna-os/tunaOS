# --- Environment Variables & Exports ---

export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export image_name := env("IMAGE_NAME", "albacore")
export default_tag := env("DEFAULT_TAG", "latest")
export bib_image := env("BIB_IMAGE", "quay.io/centos-bootc/bootc-image-builder:latest")

# --- Default Base Image (for 'regular' flavor builds) ---

export base_image := env("BASE_IMAGE", "quay.io/almalinuxorg/almalinux-bootc")
export base_image_tag := env("BASE_IMAGE_TAG", "10")

[private]
default:
    @just --list

# Check Just Syntax
check:
    #!/usr/bin/env bash
    find . -type f -name "*.just" | while read -r file; do
    	echo "Checking syntax: $file"
    	just --unstable --fmt --check -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt --check -f Justfile

# Fix Just Syntax
fix:
    #!/usr/bin/env bash
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
_build target_tag final_image_name container_file base_image_for_build image_brand platform='linux/amd64' *args:
    #!/usr/bin/env bash
    set -euxo pipefail

    BUILD_ARGS=()
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME={{ final_image_name }}")
    BUILD_ARGS+=("--build-arg" "IMAGE_BRAND={{ image_brand }}")
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

# --- LOCAL Build Pipeline ---
# Assumes 'variant' and 'image_name' are the same.

# Usage: just build <variant> [flavor]
build variant='albacore' flavor='regular' *args:
    #!/usr/bin/env bash
    set -euo pipefail

    # For local builds, the final image name is the same as the variant.
    local_image_name="{{ variant }}"

    TARGET_TAG="${local_image_name}"
    [[ "{{ flavor }}" != "regular" ]] && TARGET_TAG="${local_image_name}-{{ flavor }}"
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:{{ default_tag }}"

    BASE_FOR_BUILD=""
    IMAGE_BRAND="" # This will be set in the case statement
    CONTAINERFILE="Containerfile"
    case "{{ flavor }}" in
        "regular")
            case "{{ variant }}" in
                "yellowfin"|"almalinux-kitten") BASE_FOR_BUILD="quay.io/almalinuxorg/almalinux-bootc:10-kitten"; IMAGE_BRAND="yellowfin" ;;
                "albacore"|"almalinux")        BASE_FOR_BUILD="quay.io/almalinuxorg/almalinux-bootc:10"; IMAGE_BRAND="albacore" ;;
                "skipjack"|"centos"|"lts")    BASE_FOR_BUILD="quay.io/centos-bootc/centos-bootc:stream10"; IMAGE_BRAND="skipjack" ;;
                "bonito"|"fedora"|"bluefin")  BASE_FOR_BUILD="quay.io/fedora/fedora-bootc:42"; IMAGE_BRAND="bonito" ;;
                "bonito-rawhide"|"rawhide")   BASE_FOR_BUILD="quay.io/fedora/fedora-bootc:rawhide"; IMAGE_BRAND="bonito-rawhide" ;;
            esac
            ;;
        "dx")
            BASE_FOR_BUILD="{{ variant }}:{{ default_tag }}"
            CONTAINERFILE="Containerfile.dx"
            IMAGE_BRAND="{{ variant }}"
            ;;
        "gdx")
            BASE_FOR_BUILD="{{ variant }}-dx:{{ default_tag }}"
            CONTAINERFILE="Containerfile.gdx"
            IMAGE_BRAND="{{ variant }}"
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

    just _build "${TARGET_TAG_WITH_VERSION}" "${local_image_name}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "${IMAGE_BRAND}" "linux/amd64" {{ args }}

# --- CI Build Pipeline (for GitHub Actions) ---
# Separates 'image_name' (the final tag) from 'variant' (the base OS).

# Usage: just ci-build <image_name> <variant> [flavor]
ci-build variant='albacore' flavor='regular' platform='linux/amd64' *args:
    #!/usr/bin/env bash
    set -euo pipefail

    # The final tag is based on the 'image_name' parameter.
    TARGET_TAG="{{ variant }}"
    [[ "{{ flavor }}" != "regular" ]] && TARGET_TAG="{{ image_name }}-{{ flavor }}"
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:{{ default_tag }}"

    BASE_FOR_BUILD=""
    IMAGE_BRAND=""
    CONTAINERFILE="Containerfile"
    case "{{ flavor }}" in
        "regular")
             # The 'variant' parameter determines the base OS.
             case "{{ variant }}" in
                "yellowfin"|"almalinux-kitten") BASE_FOR_BUILD="quay.io/almalinuxorg/almalinux-bootc:10-kitten" ;;
                "albacore"|"almalinux")        BASE_FOR_BUILD="quay.io/almalinuxorg/almalinux-bootc:10" ;;
                "skipjack"|"centos"|"lts")    BASE_FOR_BUILD="quay.io/centos-bootc/centos-bootc:stream10" ;;
                "bonito"|"fedora"|"bluefin")  BASE_FOR_BUILD="quay.io/fedora/fedora-bootc:42" ;;
                "bonito-rawhide"|"rawhide")   BASE_FOR_BUILD="quay.io/fedora/fedora-bootc:rawhide" ;;
            esac
            ;;
        "dx")
            # The base image for flavored builds is also based on the final 'image_name'.
            BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ image_name }}:{{ default_tag }}"
            CONTAINERFILE="Containerfile.dx"
            ;;
        "gdx")
            BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ image_name }}-dx:{{ default_tag }}"
            CONTAINERFILE="Containerfile.gdx"
            ;;
    esac

    just _build "${TARGET_TAG_WITH_VERSION}" "{{ image_name }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "${IMAGE_BRAND}" {{ platform }} {{ args }}

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
    /usr/bin/find . -iname "*.sh" -type f -exec shfmt --write "{}" ';'
