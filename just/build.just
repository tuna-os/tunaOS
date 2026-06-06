# just/build.just — Core build pipeline

# Check if requirements are installed
[private]
_ensure-deps:
    #!/usr/bin/env bash
    if ! command -v podman &> /dev/null; then echo "podman is required"; exit 1; fi
    if ! command -v {{ yq }} &> /dev/null; then echo "yq is required. Install via brew install yq or dnf install yq"; exit 1; fi

# Private build engine.
# [build]
[private]
_build target_tag_with_version target_tag container_file base_image_for_build target_platform use_cache enable_gdx enable_hwe desktop_flavor *args: _ensure-deps
    #!/usr/bin/env bash
    export YQ="{{ yq }}"
    export COMMON_IMAGE="{{ common_image }}"
    export BREW_IMAGE="{{ brew_image }}"
    export REPO_ORGANIZATION="{{ repo_organization }}"
    export COREOS_STABLE_VERSION="{{ coreos_stable_version }}"
    export JUST="{{ just }}"
    bash ./scripts/_build.sh "$@"

# Build a TunaOS variant
# [build]
build variant='albacore' flavor='gnome' target_platform='' is_ci="0" tag='latest' chain_base_image='': _ensure-deps
    #!/usr/bin/env bash
    set -euo pipefail

    # Initialize submodules locally
    DID_INIT="0"
    if [[ "{{ is_ci }}" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]]; then
        if [[ "{{ flavor }}" == *"gnome"* ]]; then
            git submodule update --init --recursive
            DID_INIT="1"
        fi
    fi

    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'

    if [[ -z "{{ target_platform }}" ]]; then
        if [[ "{{ is_ci }}" != "1" ]]; then PLATFORM="{{ platform }}"; else
            PLATFORM=$({{ yq }} -r ".variants[] | select(.id == \"{{ variant }}\") | .platforms | join(\",\")" .github/build-config.yml)
        fi
    else PLATFORM="{{ target_platform }}"; fi

    BASE_FOR_BUILD=""
    CONTAINERFILE="Containerfile"
    ENABLE_HWE="0"
    ENABLE_GDX="0"
    PARENT_FLAVOR=""
    FLAVOR="{{ flavor }}"
    DESKTOP_FLAVOR="${FLAVOR}"

    case "${FLAVOR}" in
        "hwe") FLAVOR="gnome-hwe" ;;
        "gdx") FLAVOR="gnome-gdx" ;;
        "gdx-hwe") FLAVOR="gnome-gdx-hwe" ;;
    esac

    if [[ "${FLAVOR}" == "all" ]]; then
        readarray -t FLAVORS < <({{ yq }} -r '.variants[] | select(.id == "{{ variant }}") | .flavors[].id' .github/build-config.yml)
        for f in "${FLAVORS[@]}"; do {{ just }} build "{{ variant }}" "$f"; done
        exit 0
    elif [[ "${FLAVOR}" == "base" ]]; then
        BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
        DESKTOP_FLAVOR="base-no-de"
    elif [[ "${FLAVOR}" == "base-hwe" ]]; then
        CONTAINERFILE="Containerfile.hwe"
        ENABLE_HWE="1"
        DESKTOP_FLAVOR="base-hwe"
        PARENT_FLAVOR="base"
    elif [[ "${FLAVOR}" == "base-gdx" ]]; then
        CONTAINERFILE="Containerfile.gdx"
        ENABLE_GDX="1"
        DESKTOP_FLAVOR="base-gdx"
        PARENT_FLAVOR="base"
    elif [[ "${FLAVOR}" == *"-gdx-hwe" ]]; then
        DESKTOP_FLAVOR="${FLAVOR%-gdx-hwe}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe"
    elif [[ "${FLAVOR}" == *"-hwe" ]]; then
        DESKTOP_FLAVOR="${FLAVOR%-hwe}"; CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}"
    elif [[ "${FLAVOR}" == *"-gdx" ]]; then
        DESKTOP_FLAVOR="${FLAVOR%-gdx}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}"
    else
        DESKTOP_FLAVOR="${FLAVOR}"
        BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
    fi

    if [[ -n "${PARENT_FLAVOR}" ]]; then
        if [[ "{{ is_ci }}" = "1" ]]; then BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}:${PARENT_FLAVOR}"; else
            BASE_FOR_BUILD="localhost/{{ variant }}:${PARENT_FLAVOR}"; fi
    fi

    if [[ -n "{{ chain_base_image }}" ]] && [[ "${FLAVOR}" != "base" ]]; then
        BASE_FOR_BUILD="{{ chain_base_image }}"
    fi

    TARGET_TAG="{{ variant }}"
    TARGET_IMAGE_TAG="{{ tag }}"
    [[ "{{ tag }}" == "latest" ]] && TARGET_IMAGE_TAG="${FLAVOR}"
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:${TARGET_IMAGE_TAG}"

    if [[ "{{ is_ci }}" == "0" ]]; then
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "$PLATFORM" "1" "${ENABLE_GDX}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}"
        ./scripts/sync-build-cache.sh "${TARGET_TAG}" || true
    else
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "$PLATFORM" "0" "${ENABLE_GDX}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}"
    fi

    if [[ "$DID_INIT" == "1" ]]; then
        echo "De-initializing submodules..."
        git submodule deinit -f --all
    fi
