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
    set -euxo pipefail

    # Get image digests from image-versions.yaml
    common_image_sha=$({{ yq }} -r '.images[] | select(.name == "common") | .digest' image-versions.yaml)
    common_image_ref="{{ common_image }}@${common_image_sha}"
    brew_image_sha=$({{ yq }} -r '.images[] | select(.name == "brew") | .digest' image-versions.yaml)
    brew_image_ref="{{ brew_image }}@${brew_image_sha}"

    BUILD_ARGS=()
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME={{ target_tag }}")
    BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR={{ repo_organization }}")
    BUILD_ARGS+=("--build-arg" "BASE_IMAGE={{ base_image_for_build }}")
    BUILD_ARGS+=("--build-arg" "COMMON_IMAGE_REF=${common_image_ref}")
    BUILD_ARGS+=("--build-arg" "BREW_IMAGE_REF=${brew_image_ref}")
    BUILD_ARGS+=("--build-arg" "ENABLE_HWE={{ enable_hwe }}")
    BUILD_ARGS+=("--build-arg" "ENABLE_GDX={{ enable_gdx }}")
    BUILD_ARGS+=("--build-arg" "DESKTOP_FLAVOR={{ desktop_flavor }}")

    AKMODS_ORG=$({{ yq }} -r ".variants[] | select(.id == \"{{ target_tag }}\") | .akmods // \"ublue-os\"" .github/build-config.yml)
    BUILD_ARGS+=("--build-arg" "AKMODS_BASE=ghcr.io/${AKMODS_ORG}")

    # RHSM credentials via BuildKit-style secret. The previous --build-arg
    # approach baked them into `podman history --no-trunc` (and earlier into
    # the image ENV); --mount=type=secret in the Containerfile exposes them
    # only inside the one RUN that registers with subscription-manager and
    # never persists them in any layer.
    #
    # Only materialise the secret file if at least one RHSM var is set —
    # for non-RHEL builds (yellowfin/albacore/skipjack/bonito) this stays
    # empty and no secret is passed.
    RHSM_SECRET_FILE=""
    if [[ -n "${RHSM_USER:-}${RHSM_PASSWORD:-}${RHSM_ORG:-}${RHSM_ACTIVATION_KEY:-}" ]]; then
        RHSM_SECRET_FILE=$(mktemp)
        # shellcheck disable=SC2064 # cleanup must run with the captured path
        trap "rm -f '${RHSM_SECRET_FILE}'" EXIT
        chmod 0600 "${RHSM_SECRET_FILE}"
        {
            printf 'export RHSM_USER=%q\n'           "${RHSM_USER:-}"
            printf 'export RHSM_PASSWORD=%q\n'       "${RHSM_PASSWORD:-}"
            printf 'export RHSM_ORG=%q\n'            "${RHSM_ORG:-}"
            printf 'export RHSM_ACTIVATION_KEY=%q\n' "${RHSM_ACTIVATION_KEY:-}"
        } > "${RHSM_SECRET_FILE}"
        BUILD_ARGS+=("--secret" "id=rhsm,src=${RHSM_SECRET_FILE}")
    fi

    if [[ "{{ enable_hwe }}" -eq "1" ]] || [[ "{{ target_tag }}" == bonito* ]]; then
        BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=coreos-stable-{{ coreos_stable_version }}")
        BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=coreos-stable-{{ coreos_stable_version }}")
    else
        BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=centos-10")
        BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=centos-10")
    fi
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME_VARIANT={{ target_tag }}")

    if [[ -z "$(git status -s)" ]]; then
        BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
    else
        BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=dirty")
    fi

    if [[ "{{ use_cache }}" == "1" ]]; then
        readarray -t CACHE_MOUNTS < <(./scripts/setup-build-cache.sh "{{ target_tag }}")
        BUILD_ARGS+=("${CACHE_MOUNTS[@]}")
    fi

    DESKTOP_FLAVOR="{{ desktop_flavor }}"
    PRE_CHUNK_TAG="{{ target_tag_with_version }}-pre-chunk"

    echo "==> Building ${DESKTOP_FLAVOR} stage..."

    # Pass 1: Build the target DE stage directly — no unused stages built
    podman build \
        --security-opt label=disable \
        --dns=8.8.8.8 \
        --platform "{{ target_platform }}" \
        --target="${DESKTOP_FLAVOR}" \
        "${BUILD_ARGS[@]}" \
        --tag "${PRE_CHUNK_TAG}" \
        {{ args }} \
        --pull=newer \
        --file "{{ container_file }}" \
        .

    echo "==> Running chunkah on ${PRE_CHUNK_TAG}..."

    # Ensure the chunkah image is available. Try the published image first,
    # then fall back to building from source if it's not pullable.
    CHUNKAH_IMAGE="quay.io/coreos/chunkah:latest"
    if ! podman image inspect "${CHUNKAH_IMAGE}" &>/dev/null; then
        if ! podman pull "${CHUNKAH_IMAGE}" 2>/dev/null; then
            echo "==> chunkah image not pullable, building from source..."
            ./scripts/build-chunkah.sh
            CHUNKAH_IMAGE="localhost/chunkah:latest"
        fi
    fi

    # Use a clean temp dir to avoid SELinux relabeling issues with existing files in PWD
    CHUNK_OUT=$(mktemp -d)
    # Pass 2: Run chunkah externally against the built image
    podman run --rm \
        --security-opt label=disable \
        --dns=8.8.8.8 \
        --entrypoint="" \
        -v "${CHUNK_OUT}:/run/out:Z" \
        --mount "type=image,source=${PRE_CHUNK_TAG},target=/chunkah" \
        "${CHUNKAH_IMAGE}" \
        sh -c 'chunkah build > /run/out/out.ociarchive'
    mv "${CHUNK_OUT}/out.ociarchive" out.ociarchive
    rm -rf "${CHUNK_OUT}"

    echo "==> Applying labels from OCI archive..."

    # Pass 3: Load archive into podman storage via podman load, then apply OCI labels.
    # podman load guarantees the same graphRoot as the subsequent podman build.
    # skopeo copy is avoided here because CI uses ublue-os/container-storage-action
    # which mounts a BTRFS graphRoot for podman; skopeo defaults to overlay and writes
    # to a different path, causing podman build to fall back to a remote registry pull.

    # Prune ALL unused images from BTRFS storage before loading the rechunked archive.
    # Targeted rmi of just pre-chunk + chain base isn't sufficient: multi-stage FROM
    # images (e.g. akmods-nvidia-open) are also left in BTRFS and cause disk pressure
    # that triggers a podman storage index bug ("image not known" after load).
    # Containerfile.final only needs the rechunked archive (loaded next), so it's safe
    # to remove everything else at this point.
    podman system prune -af 2>/dev/null || true

    RECHUNKED_REF="localhost/{{ target_tag_with_version }}-rechunked-$$"
    LOADED_ID=$(podman load --input out.ociarchive | awk '/Loaded image/{print $NF}')
    rm -f out.ociarchive  # free disk immediately after load; don't hold archive while build runs
    if [[ -z "${LOADED_ID}" ]]; then
        echo "ERROR: podman load produced no image ID; the OCI archive may be corrupt or disk full" >&2
        exit 1
    fi
    podman tag "${LOADED_ID}" "${RECHUNKED_REF}"

    podman build \
        --security-opt label=disable \
        --dns=8.8.8.8 \
        "${BUILD_ARGS[@]}" \
        --build-arg "RECHUNKED_BASE=${RECHUNKED_REF}" \
        --tag "{{ target_tag_with_version }}" \
        --file "Containerfile.final" \
        .

    podman rmi "${RECHUNKED_REF}" 2>/dev/null || true

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
