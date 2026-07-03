export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export default_tag := env("DEFAULT_TAG", "latest")
export common_image := env("COMMON_IMAGE", "ghcr.io/projectbluefin/common")
export brew_image := env("BREW_IMAGE", "ghcr.io/ublue-os/brew")
export coreos_stable_version := env("COREOS_STABLE_VERSION", "43")
export enable_sshd_var := env("ENABLE_SSHD", "0")
just := just_executable()
arch := arch()
yq := `which yq`
export platform := env("PLATFORM", if arch == "x86_64" { if `rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; echo $?` == "0" { "linux/amd64/v2" } else { "linux/amd64" } } else if arch == "arm64" { "linux/arm64" } else if arch == "aarch64" { "linux/arm64" } else { error("Unsupported ARCH '" + arch + "'. Supported values are 'x86_64', 'aarch64', and 'arm64'.") })

import 'just/utilities.just'

# ==============================================================================
#  BUILD PIPELINE
# ==============================================================================

# Check if requirements are installed
[private]
_ensure-deps:
    #!/usr/bin/env bash
    if ! command -v "{{ yq }}" &> /dev/null; then
        echo "Missing requirement: 'yq' is not installed."
        echo "Please install yq (e.g. 'brew install yq' or download from https://github.com/mikefarah/yq)"
        exit 1
    fi

# Private build engine.
[private]
_build target_tag_with_version target_tag container_file base_image_for_build target_platform use_cache enable_gdx enable_hwe desktop_flavor is_ci_build enable_sshd_build *args: _ensure-deps
    #!/usr/bin/env bash
    set -euxo pipefail

    # Source registry abstraction for configurable mirror support (RFC-009)
    source scripts/_registry.sh

    # Get image digests from image-versions.yaml
    common_image_sha=$({{ yq }} -r '.images[] | select(.name == "common") | .digest' image-versions.yaml)
    common_image_ref="{{ common_image }}@${common_image_sha}"
    brew_image_sha=$({{ yq }} -r '.images[] | select(.name == "brew") | .digest' image-versions.yaml)
    brew_image_ref="{{ brew_image }}@${brew_image_sha}"

    BUILD_ARGS=()
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME={{ target_tag }}")
    BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR={{ repo_organization }}")
    BUILD_ARGS+=("--build-arg" "IMAGE_REGISTRY=${IMAGE_REGISTRY:-ghcr.io}")
    BUILD_ARGS+=("--build-arg" "BASE_IMAGE={{ base_image_for_build }}")
    BUILD_ARGS+=("--build-arg" "COMMON_IMAGE_REF=${common_image_ref}")
    BUILD_ARGS+=("--build-arg" "BREW_IMAGE_REF=${brew_image_ref}")
    BUILD_ARGS+=("--build-arg" "ENABLE_HWE={{ enable_hwe }}")
    BUILD_ARGS+=("--build-arg" "ENABLE_NVIDIA={{ enable_gdx }}")
    BUILD_ARGS+=("--build-arg" "DESKTOP_FLAVOR={{ desktop_flavor }}")
    BUILD_ARGS+=("--build-arg" "ENABLE_SSHD={{ enable_sshd_build }}")

    AKMODS_ORG=$({{ yq }} -r ".variants[] | select(.id == \"{{ target_tag }}\") | .akmods // \"ublue-os\"" .github/build-config.yml)
    # Resolve akmods registry via registry-map; falls back to ghcr.io/${AKMODS_ORG} if not mapped
    AKMODS_REGISTRY_BASE="$(registry_ref akmods 2>/dev/null || echo "ghcr.io/${AKMODS_ORG}")"
    BUILD_ARGS+=("--build-arg" "AKMODS_BASE=${AKMODS_REGISTRY_BASE}")

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

    # Zirconium system files feed the niri desktop stages (all variants) and
    # grouper (RFC 010). Pin the image ref via image-versions.yaml, same as
    # common/brew — without this the Containerfile ARG default floats on
    # :latest and builds aren't reproducible.
    zirconium_image_sha=$({{ yq }} -r '.images[] | select(.name == "zirconium") | .digest' image-versions.yaml)
    BUILD_ARGS+=("--build-arg" "ZIRCONIUM_IMAGE_REF=ghcr.io/zirconium-dev/zirconium@${zirconium_image_sha}")

    # build_scripts/*.sh are injected into RUN steps via
    # --mount=type=bind,from=context (not COPY), so their content never
    # participates in buildah's layer-cache key — editing a script alone
    # doesn't invalidate the layer that ran it. Hash the directory and pass
    # it as a build-arg (consumed as an early ENV in the Containerfiles) so
    # the cache correctly invalidates exactly when these scripts change,
    # independent of SHA_HEAD_SHORT (which changes every commit and stays
    # out of this position deliberately, to keep cross-commit caching for
    # commits that don't touch build_scripts/ at all).
    build_scripts_hash=$(find build_scripts -type f -name '*.sh' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
    BUILD_ARGS+=("--build-arg" "BUILD_SCRIPTS_HASH=${build_scripts_hash}")

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

    # Use buildah in CI (for layer caching via actions/cache), podman locally
    # (the local buildah wrapper tries to pull localhost/buildah-tool which fails).
    BUILDER="podman"
    PULL_FLAG="--pull=newer"
    if [[ "{{ is_ci_build }}" == "1" ]] && command -v buildah &>/dev/null; then
        BUILDER="buildah"
        PULL_FLAG="--pull-always"
    fi

    # Pass 1: Build the target DE stage directly — no unused stages built
    ${BUILDER} build \
        --security-opt label=disable \
        --dns=8.8.8.8 \
        --platform "{{ target_platform }}" \
        --target="${DESKTOP_FLAVOR}" \
        "${BUILD_ARGS[@]}" \
        --tag "${PRE_CHUNK_TAG}" \
        {{ args }} \
        ${PULL_FLAG} \
        --file "{{ container_file }}" \
        ${BUILDAH_CACHE_FLAGS:-} \
        .

    # PR/CI validation builds don't publish — the rechunk exists purely for
    # client pull efficiency, so let callers skip passes 2-3 (~10 min).
    if [[ "${SKIP_RECHUNK:-0}" == "1" ]]; then
        echo "==> SKIP_RECHUNK=1 — tagging pre-chunk image as final (no chunkah/relabel)"
        ${BUILDER} tag "${PRE_CHUNK_TAG}" "{{ target_tag_with_version }}"
        exit 0
    fi

    echo "==> Running chunkah on ${PRE_CHUNK_TAG}..."

    # Ensure the chunkah image is available. Try the published image first,
    # then fall back to building from source if it's not pullable.
    # quay.io/coreos/chunkah:latest is the canonical chunkah image.
    # Override via CHUNKAH_IMAGE env var or registry-map.yaml registry_ref.
    if [[ -z "${CHUNKAH_IMAGE:-}" ]]; then
        CHUNKAH_IMAGE="quay.io/coreos/chunkah:latest"
    fi
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
    # --network host: chunkah needs no networking (reads from mounted image,
    # writes to mounted output dir). Avoids podman userspace-network-NS
    # (pasta) which fails inside nested VMs (KubeVirt) that lack user
    # namespace pivot_root capability.
    podman run --rm \
        --security-opt label=disable \
        --network host \
        --entrypoint="" \
        -v "${CHUNK_OUT}:/run/out:Z" \
        --mount "type=image,source=${PRE_CHUNK_TAG},target=/chunkah" \
        "${CHUNKAH_IMAGE}" \
        sh -c 'chunkah build > /run/out/out.ociarchive'
    mv "${CHUNK_OUT}/out.ociarchive" out.ociarchive
    rm -rf "${CHUNK_OUT}"

    echo "==> Applying labels from OCI archive..."

    # Pass 3: Load archive into podman storage via podman load, then apply OCI labels.
    # podman load guarantees the same graphRoot as the subsequent buildah build.
    # skopeo copy is avoided here because CI uses ublue-os/container-storage-action
    # which mounts a BTRFS graphRoot for podman; skopeo defaults to overlay and writes
    # to a different path, causing buildah build to fall back to a remote registry pull.

    # Prune ALL unused images from BTRFS storage before loading the rechunked archive.
    # Targeted rmi of just pre-chunk + chain base isn't sufficient: multi-stage FROM
    # images (e.g. akmods-nvidia-open) are also left in BTRFS and cause disk pressure
    # that triggers a podman storage index bug ("image not known" after load).
    # Containerfile.final only needs the rechunked archive (loaded next), so it's safe
    # to remove everything else at this point.
    podman system prune -af 2>/dev/null || true

    RECHUNKED_REF="localhost/{{ target_tag_with_version }}-rechunked-$$"
    LOADED_ID=$(TMPDIR=${TMPDIR:-/tmp} podman load --input out.ociarchive | awk '/Loaded image/{print $NF}')
    rm -f out.ociarchive  # free disk immediately after load; don't hold archive while build runs
    if [[ -z "${LOADED_ID}" ]]; then
        echo "ERROR: podman load produced no image ID; the OCI archive may be corrupt or disk full" >&2
        exit 1
    fi
    podman tag "${LOADED_ID}" "${RECHUNKED_REF}"

    ${BUILDER} build \
        --security-opt label=disable \
        --dns=8.8.8.8 \
        "${BUILD_ARGS[@]}" \
        --build-arg "RECHUNKED_BASE=${RECHUNKED_REF}" \
        --tag "{{ target_tag_with_version }}" \
        --file "Containerfile.final" \
        .

    ${BUILDER} rmi "${RECHUNKED_REF}" 2>/dev/null || true

# Build a TunaOS variant
build variant='albacore' flavor='gnome' target_platform='' is_ci="0" tag='latest' chain_base_image='' enable_sshd="0": _ensure-deps
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
    # RFC 010: grouper (Ubuntu) uses Containerfile.ubuntu
    if [[ "{{ variant }}" == "grouper" ]]; then
        CONTAINERFILE="Containerfile.ubuntu"
    fi
    ENABLE_HWE="0"
    ENABLE_NVIDIA="0"
    ENABLE_SSHD="{{ enable_sshd_var }}"
    PARENT_FLAVOR=""
    FLAVOR="{{ flavor }}"
    DESKTOP_FLAVOR="${FLAVOR}"

    case "${FLAVOR}" in
        "hwe") FLAVOR="gnome-hwe" ;;
        "nvidia") FLAVOR="gnome-nvidia" ;;
        "gdx-hwe") FLAVOR="gnome-nvidia-hwe" ;;
    esac

    if [[ "${FLAVOR}" == "all" ]]; then
        readarray -t FLAVORS < <({{ yq }} -r '.variants[] | select(.id == "{{ variant }}") | .flavors[].id' .github/build-config.yml)
        for f in "${FLAVORS[@]}"; do {{ just }} build "{{ variant }}" "$f"; done
        exit 0
    elif [[ "${FLAVOR}" == "base" ]]; then
        BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
        DESKTOP_FLAVOR="base-no-de"
        # grouper's base-no-de is intentionally pre-bootcify (apt still intact so
        # the DE stages can layer packages); the bootcified base is the `base`
        # stage, which runs finalize.sh (mount-system + bootc container lint).
        if [[ "{{ variant }}" == "grouper" ]]; then DESKTOP_FLAVOR="base"; fi
    elif [[ "${FLAVOR}" == "base-hwe" ]]; then
        CONTAINERFILE="Containerfile.hwe"
        ENABLE_HWE="1"
        DESKTOP_FLAVOR="base-hwe"
        PARENT_FLAVOR="base"
    elif [[ "${FLAVOR}" == "base-nvidia" ]]; then
        CONTAINERFILE="Containerfile.nvidia"
        ENABLE_NVIDIA="1"
        DESKTOP_FLAVOR="base-nvidia"
        PARENT_FLAVOR="base"
    elif [[ "{{ variant }}" != "grouper" && "${FLAVOR}" == *"-nvidia-hwe" ]]; then
        DESKTOP_FLAVOR="${FLAVOR%-nvidia-hwe}"; CONTAINERFILE="Containerfile.nvidia"; ENABLE_NVIDIA="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe"
    elif [[ "{{ variant }}" != "grouper" && "${FLAVOR}" == *"-hwe" ]]; then
        DESKTOP_FLAVOR="${FLAVOR%-hwe}"; CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}"
    elif [[ "{{ variant }}" != "grouper" && "${FLAVOR}" == *"-nvidia" ]]; then
        DESKTOP_FLAVOR="${FLAVOR%-nvidia}"; CONTAINERFILE="Containerfile.nvidia"; ENABLE_NVIDIA="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}"
    else
        DESKTOP_FLAVOR="${FLAVOR}"
        BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
    fi

    if [[ -n "${PARENT_FLAVOR}" ]]; then
        # CI chains on the -testing stream tag: it is pushed by the manifest
        # job of the parent's build in THIS run, before the parent's boot
        # gate promotes the bare tag. Chaining on the bare tag would build
        # stage-3 images against last week's parent.
        if [[ "{{ is_ci }}" = "1" ]]; then BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}:${PARENT_FLAVOR}-testing"; else
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
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "$PLATFORM" "1" "${ENABLE_NVIDIA}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}" "{{ is_ci }}" "{{ enable_sshd }}"
        ./scripts/sync-build-cache.sh "${TARGET_TAG}" || true
    else
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "$PLATFORM" "0" "${ENABLE_NVIDIA}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}" "{{ is_ci }}" "{{ enable_sshd }}"
    fi

    if [[ "$DID_INIT" == "1" ]]; then
        echo "De-initializing submodules..."
        git submodule deinit -f --all
    fi

# Build a TunaOS live ISO via tacklebox (no Anaconda, dmsquash-live + sd-boot)
# Build a live ISO via tacklebox (replaces deprecated bootc-image-builder approach)
iso variant='skipjack' flavor='gnome' repo='local' tag='' dev='0':
    #!/usr/bin/env bash
    set -euo pipefail
    _tag="{{ tag }}"
    [[ -z "$_tag" ]] && _tag="{{ flavor }}"
    if [[ "{{ dev }}" == "1" ]] && [[ "{{ repo }}" == "local" ]]; then
        # Dev mode: build with SSH enabled for e2e testing
        {{ just }} build "{{ variant }}" "{{ flavor }}" "" "0" "$_tag" "" "1"
    fi
    sudo -E bash ./scripts/build-iso-tacklebox.sh "{{ variant }}" "{{ flavor }}" "{{ repo }}" "$_tag"

# Build ONE combined dedup ISO containing every desktop in an iso_group (#455).
# group: '' / default (flagship gnome+hwe), community (kde/cosmic/niri), nvidia.
iso-group variant='yellowfin' group='default' repo='ghcr':
    sudo bash ./scripts/build-iso-group.sh "{{ variant }}" "{{ group }}" "{{ repo }}"
# Generate a QCOW2 disk image using bootc install to-disk (via loopback in a privileged container)
qcow2 variant flavor='gnome' repo='local' tag='':
    #!/usr/bin/env bash
    set -euo pipefail

    IMG_REF=""
    if [[ "{{ variant }}" == *":"* || "{{ variant }}" == *"/"* ]]; then
        IMG_REF="{{ variant }}"
        OUTPUT_NAME=$(echo "{{ variant }}" | awk -F'/' '{print $NF}' | awk -F':' '{print $1}')
    else
        if [ "{{ repo }}" = "local" ]; then
            {{ just }} build {{ variant }} {{ flavor }}
        fi
        TAG="{{ tag }}"
        [[ -z "$TAG" ]] && TAG="{{ flavor }}"

        if [ "{{ repo }}" = "ghcr" ]; then IMG_REF="ghcr.io/{{ repo_organization }}/{{ variant }}:$TAG"
        elif [ "{{ repo }}" = "local" ]; then IMG_REF="localhost/{{ variant }}:$TAG"
        else exit 1; fi
        OUTPUT_NAME="{{ variant }}"
    fi

    OUTPUT="${OUTPUT_NAME}.qcow2"
    RAW_FILE="${OUTPUT_NAME}.raw"
    echo "==> Generating $OUTPUT from $IMG_REF using bootc install to-disk..."

    # Ensure root podman storage has the LATEST version of this image.
    # (bootc install to-disk runs as root and reads from root storage)
    # Skip the expensive save|load when root storage already has it — e.g.
    # CI builds run under sudo so the image never touches user storage.
    if [[ "${IMG_REF}" == localhost/* ]] || [[ "${IMG_REF}" == *"/"* && "${IMG_REF}" != ghcr* ]]; then
        if sudo podman image exists "$IMG_REF"; then
            echo "==> $IMG_REF already in root podman storage; skipping sync"
        elif podman image exists "$IMG_REF"; then
            echo "==> Syncing $IMG_REF into root podman storage..."
            podman save "$IMG_REF" | sudo podman load
        else
            echo "==> $IMG_REF not in local storage; bootc will pull it"
        fi
    fi

    # Create a sparse raw disk file (40 GiB)
    rm -f "$RAW_FILE"
    truncate -s 40G "$RAW_FILE"
    RAW_ABS="$(realpath "$RAW_FILE")"

    # bootc install to-disk runs from inside the container image so it can
    # access its own OSTree commit. --via-loopback writes to a regular file
    # instead of a real block device. --generic-image skips firmware flashing
    # and installs all bootloader types (required for disk images).
    #
    # We also mount the correct install config from the repo over the top of
    # whatever is baked into the image, so stale cached builds can't break
    # the TOML parse step.
    INSTALL_TOML="$(pwd)/system_files/usr/lib/bootc/install/00-tunaos.toml"

    # Collect the local user's SSH public keys to inject into root's authorized_keys
    SSH_PUBKEYS_FILE=""
    TMPKEYS=$(mktemp)
    for pub in ~/.ssh/id_ed25519.pub ~/.ssh/id_rsa.pub ~/.ssh/id_ecdsa.pub ~/.ssh/id_dsa.pub; do
        [[ -f "$pub" ]] && cat "$pub" >> "$TMPKEYS"
    done
    # Also pick up any additional id_*.pub files not already included
    while IFS= read -r pub; do
        cat "$pub" >> "$TMPKEYS"
    done < <(ls ~/.ssh/id_*.pub 2>/dev/null | grep -vE 'id_ed25519|id_rsa|id_ecdsa|id_dsa' || true)
    # Also include the Lima VM key so Lima-booted VMs are accessible via SSH
    [[ -f ~/.lima/_config/user.pub ]] && cat ~/.lima/_config/user.pub >> "$TMPKEYS"
    if [[ -s "$TMPKEYS" ]]; then
        SSH_PUBKEYS_FILE="$TMPKEYS"
        echo "==> Injecting SSH authorized keys for root from ~/.ssh/id_*.pub..."
    else
        rm -f "$TMPKEYS"
        echo "==> No local SSH public keys found; skipping root SSH key injection."
    fi

    SSH_VOL_ARGS=()
    SSH_KEY_ARGS=()
    if [[ -n "$SSH_PUBKEYS_FILE" ]]; then
        SSH_VOL_ARGS=("-v" "${SSH_PUBKEYS_FILE}:/run/root-authorized-keys:ro")
        SSH_KEY_ARGS=("--root-ssh-authorized-keys" "/run/root-authorized-keys")
    fi

    # grouper (Ubuntu) has no bootupd package available via apt, so it ships
    # systemd-boot instead and installs via bootc's composefs-native backend,
    # which doesn't shell out to bootupd for bootloader management.
    COMPOSEFS_ARGS=()
    [[ "$OUTPUT_NAME" == grouper* ]] && COMPOSEFS_ARGS=(--composefs-backend)

    echo "==> Running bootc install to-disk (this takes a few minutes)..."
    sudo podman run \
        --rm \
        --privileged \
        --pid=host \
        -v /dev:/dev \
        -v /var/lib/containers:/var/lib/containers \
        -v "${RAW_ABS}:/disk.img" \
        -v "${INSTALL_TOML}:/usr/lib/bootc/install/00-tunaos.toml:ro" \
        "${SSH_VOL_ARGS[@]}" \
        --security-opt label=disable \
        "$IMG_REF" \
        bootc install to-disk \
            --via-loopback \
            --generic-image \
            "${COMPOSEFS_ARGS[@]}" \
            --karg console=ttyS0 --karg console=tty0 \
            "${SSH_KEY_ARGS[@]}" \
            --source-imgref "containers-storage:${IMG_REF}" \
            /disk.img

    [[ -n "$SSH_PUBKEYS_FILE" ]] && rm -f "$SSH_PUBKEYS_FILE"

    # Convert raw → qcow2 for Lima/QEMU consumption
    echo "==> Converting raw → qcow2..."
    if ! command -v qemu-img &>/dev/null; then
        echo "Error: 'qemu-img' not found. Install qemu-img (e.g. sudo dnf install qemu-img)"
        exit 1
    fi
    qemu-img convert -f raw -O qcow2 -p "$RAW_FILE" "$OUTPUT"
    rm -f "$RAW_FILE"
    sudo chown "${SUDO_UID:-$(id -u)}:${SUDO_GID:-$(id -g)}" "$OUTPUT" 2>/dev/null || chown "$(id -u):$(id -g)" "$OUTPUT" 2>/dev/null || true
    echo "✓ Created $OUTPUT"

# Test an image locally using Lima VM (automated display manager check)
test-vm variant flavor='gnome':
    #!/usr/bin/env bash
    set -euo pipefail
    bash ./scripts/test-vm.sh {{ variant }} {{ flavor }}

# Boot an image in QEMU via browser (uses ghcr.io/qemus/qemu)
run-qcow2 variant flavor='gnome':
    @{{ just }} _run-vm qcow2 {{ variant }} {{ flavor }}

# Boot an ISO in QEMU via browser
run-iso variant flavor='gnome' iso_file='':
    @{{ just }} _run-vm iso {{ variant }} {{ flavor }} "{{ iso_file }}"

# Build a qcow2 image and boot it in a QEMU container with a built-in web VNC UI

# Pass rebuild=1 to force a fresh image build even if one already exists
demo variant='albacore' flavor='gnome' rebuild='0':
    #!/usr/bin/env bash
    set -euo pipefail

    if [[ -f "{{ variant }}-{{ flavor }}.qcow2" ]]; then
        QCOW2_FILE="{{ variant }}-{{ flavor }}.qcow2"
    else
        QCOW2_FILE="{{ variant }}.qcow2"
    fi

    if [[ "{{ rebuild }}" == "1" ]] || [[ ! -f "${QCOW2_FILE}" ]]; then
        echo "==> Building qcow2..."
        {{ just }} qcow2 "{{ variant }}" "{{ flavor }}"
        if [[ -f "{{ variant }}-{{ flavor }}.qcow2" ]]; then QCOW2_FILE="{{ variant }}-{{ flavor }}.qcow2"
        else QCOW2_FILE="{{ variant }}.qcow2"; fi
    fi

    if [[ ! -f "${QCOW2_FILE}" ]]; then
        echo "Error: ${QCOW2_FILE} not found after build."
        exit 1
    fi

    {{ just }} _run-vm qcow2 "{{ variant }}" "{{ flavor }}"

# Build a live ISO and boot it in a QEMU container with a built-in web VNC UI

# Pass rebuild=1 to force a fresh ISO build even if one already exists
demo-iso variant='skipjack' flavor='gnome' rebuild='0':
    #!/usr/bin/env bash
    set -euo pipefail

    BUILD_DIR=".build/live-iso/{{ variant }}-{{ flavor }}"
    ISO_FILE=$(find "${BUILD_DIR}" -maxdepth 1 -name "*.iso" 2>/dev/null | head -1 || true)

    if [[ "{{ rebuild }}" == "1" ]] || [[ -z "${ISO_FILE}" ]] || [[ ! -f "${ISO_FILE}" ]]; then
        echo "==> Building live ISO..."
        {{ just }} live-iso "{{ variant }}" "{{ flavor }}" local
        ISO_FILE=$(find "${BUILD_DIR}" -maxdepth 1 -name "*.iso" 2>/dev/null | head -1 || true)
    fi

    if [[ -z "${ISO_FILE}" ]] || [[ ! -f "${ISO_FILE}" ]]; then
        echo "Error: ISO not found in ${BUILD_DIR}. Check build output."
        exit 1
    fi

    {{ just }} _run-vm iso "{{ variant }}" "{{ flavor }}" "$(realpath "${ISO_FILE}")"

# Internal: start a Lima VM from a qcow2 or live ISO, then wire up a noVNC container
[private]
_lima-novnc vm_name type image_path:
    #!/usr/bin/env bash
    set -euo pipefail

    VM_NAME="{{ vm_name }}"
    TYPE="{{ type }}"
    IMAGE_PATH="{{ image_path }}"

    if ! command -v limactl &>/dev/null; then
        echo "Error: 'limactl' not found. Install Lima: https://lima-vm.io/"
        exit 1
    fi

    ARCH=$(uname -m)
    [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"

    # Remove any pre-existing VM with this name
    if limactl list -q 2>/dev/null | grep -q "^${VM_NAME}$"; then
        echo "==> Removing existing VM: ${VM_NAME}"
        limactl stop -f "${VM_NAME}" 2>/dev/null || true
        limactl delete "${VM_NAME}"
    fi

    CONFIG_FILE=$(mktemp --suffix=.yaml)
    CLEANUP_FILES=("${CONFIG_FILE}")
    trap 'rm -f "${CLEANUP_FILES[@]}" 2>/dev/null || true' EXIT

    if [[ "${TYPE}" == "iso" ]]; then
        # Create a sparse target disk; QEMU boots from the ISO via -cdrom
        EMPTY_DISK=$(mktemp --suffix=.qcow2)
        CLEANUP_FILES+=("${EMPTY_DISK}")
        qemu-img create -f qcow2 "${EMPTY_DISK}" 32G

        # plain=true skips SSH/cloud-init checks so Lima doesn't block waiting for a live OS
        echo "images:" > "${CONFIG_FILE}"
        echo "  - location: ${EMPTY_DISK}" >> "${CONFIG_FILE}"
        echo "    arch: ${LIMA_ARCH}" >> "${CONFIG_FILE}"
        echo "video:" >> "${CONFIG_FILE}"
        echo "  display: \"vnc\"" >> "${CONFIG_FILE}"
        echo "memory: \"4GiB\"" >> "${CONFIG_FILE}"
        echo "cpus: 4" >> "${CONFIG_FILE}"
        echo "plain: true" >> "${CONFIG_FILE}"
        echo "qemu:" >> "${CONFIG_FILE}"
        echo "  extraArgs:" >> "${CONFIG_FILE}"
        echo "    - \"-cdrom\"" >> "${CONFIG_FILE}"
        echo "    - ${IMAGE_PATH}" >> "${CONFIG_FILE}"
        echo "    - \"-boot\"" >> "${CONFIG_FILE}"
        echo "    - \"order=d,menu=on\"" >> "${CONFIG_FILE}"
    else
        # qcow2: boot directly; plain=true because bootc images may not have cloud-init
        echo "images:" > "${CONFIG_FILE}"
        echo "  - location: ${IMAGE_PATH}" >> "${CONFIG_FILE}"
        echo "    arch: ${LIMA_ARCH}" >> "${CONFIG_FILE}"
        echo "video:" >> "${CONFIG_FILE}"
        echo "  display: \"vnc\"" >> "${CONFIG_FILE}"
        echo "memory: \"4GiB\"" >> "${CONFIG_FILE}"
        echo "cpus: 4" >> "${CONFIG_FILE}"
        echo "plain: true" >> "${CONFIG_FILE}"
    fi

    echo "==> Starting Lima VM: ${VM_NAME}"
    limactl start --name="${VM_NAME}" --tty=false "${CONFIG_FILE}"

    # Resolve VNC host:port — Lima writes the QEMU display string to vncdisplay
    VNC_DISPLAY=""
    VNC_DISPLAY=$(limactl list --json 2>/dev/null | jq -r "select(.name==\"${VM_NAME}\") | .video.vnc.display // empty" || true)
    if [[ -z "${VNC_DISPLAY}" ]]; then
        VNC_FILE="${HOME}/.lima/${VM_NAME}/vncdisplay"
        [[ -f "${VNC_FILE}" ]] && VNC_DISPLAY=$(cat "${VNC_FILE}")
    fi

    if [[ -z "${VNC_DISPLAY}" ]]; then
        echo "Error: could not determine VNC display for ${VM_NAME}."
        echo "Check: ls ~/.lima/${VM_NAME}/"
        exit 1
    fi

    VNC_DISPLAY="${VNC_DISPLAY%%,*}"      # strip trailing options like ",to=9"
    VNC_HOST="${VNC_DISPLAY%:*}"
    VNC_DISP_NUM="${VNC_DISPLAY##*:}"
    VNC_PORT=$(( 5900 + VNC_DISP_NUM ))

    # Lima generates a VNC password stored alongside the display file
    VNC_PASS_FILE="${HOME}/.lima/${VM_NAME}/vncpassword"
    VNC_PASS=""
    [[ -f "${VNC_PASS_FILE}" ]] && VNC_PASS=$(cat "${VNC_PASS_FILE}")

    # Find a free port for the noVNC web UI
    NOVNC_PORT=6080
    while ss -tln 2>/dev/null | grep -q ":${NOVNC_PORT} "; do
        NOVNC_PORT=$(( NOVNC_PORT + 1 ))
    done

    echo "==> VNC at ${VNC_HOST}:${VNC_PORT}"
    echo "==> Starting noVNC on port ${NOVNC_PORT}..."

    # Remove any leftover noVNC container from a previous run
    podman rm -f "${VM_NAME}-novnc" 2>/dev/null || true

    # Use registry-ref resolved novnc image (RFC-009: configurable mirror support).
    # --network host lets the container reach Lima's VNC on 127.0.0.1.
    podman run -d --rm \
        --name "${VM_NAME}-novnc" \
        --network host \
        "$(source scripts/_registry.sh 2>/dev/null && registry_ref novnc || echo 'ghcr.io/novnc/novnc:latest')" \
        /usr/share/novnc/utils/novnc_proxy \
            --listen "${NOVNC_PORT}" \
            --vnc "${VNC_HOST}:${VNC_PORT}"

    # Build the local URL. Password intentionally NOT embedded in URL —
    # novnc_proxy uses --passwd for server-side auth; browser prompts users.
    # Embedding passwords in URLs exposes them in shell history, ps output, and browser history.
    NOVNC_PARAMS="vnc.html?autoconnect=1"
    LOCAL_URL="http://127.0.0.1:${NOVNC_PORT}/${NOVNC_PARAMS}&host=127.0.0.1&port=${NOVNC_PORT}"

    # Detect Tailscale IP for remote access
    TAILSCALE_IP=""
    if command -v tailscale &>/dev/null; then
        TAILSCALE_IP=$(tailscale ip -4 2>/dev/null | head -1 || true)
    fi
    if [[ -z "${TAILSCALE_IP}" ]]; then
        TAILSCALE_IP=$(ip addr show tailscale0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -1 || true)
    fi

    echo "==> Waiting for noVNC to be ready..."
    for _i in $(seq 1 20); do
        curl -sf "http://127.0.0.1:${NOVNC_PORT}/" &>/dev/null && break || sleep 1
    done

    echo ""
    echo "=============================="
    echo " VM:       ${VM_NAME}"
    echo " Local:    ${LOCAL_URL}"
    if [[ -n "${TAILSCALE_IP}" ]]; then
        TAILNET_URL="http://${TAILSCALE_IP}:${NOVNC_PORT}/${NOVNC_PARAMS}&host=${TAILSCALE_IP}&port=${NOVNC_PORT}"
        echo " Tailnet:  ${TAILNET_URL}"
    fi
    [[ -n "${VNC_PASS}" ]] && echo " Password: ${VNC_PASS}"
    echo "=============================="
    echo " Stop: limactl stop ${VM_NAME} && podman stop ${VM_NAME}-novnc"
    echo ""

    if command -v xdg-open &>/dev/null; then
        xdg-open "${LOCAL_URL}" || true
    fi

# Verify an image using Lima (automated DM check)
verify variant flavor='gnome':
    #!/usr/bin/env bash
    set -euo pipefail
    ./scripts/verify-image.sh "{{ variant }}" "{{ flavor }}"

# Boot-gate a published (or local) image via corral: builds a disk with
# bootc, boots it (KubeVirt when your kubeconfig reaches a cluster, local
# QEMU otherwise — needs tuna-os/corral#74), waits for SSH, then runs the
# tier-1 desktop health checks. One command, same behavior locally and in CI.
boot-gate variant flavor='gnome' tag='':
    #!/usr/bin/env bash
    set -euo pipefail
    command -v corral >/dev/null || { echo "corral not installed: go install github.com/tuna-os/corral@latest"; exit 77; }
    TAG="{{ tag }}"; [[ -z "$TAG" ]] && TAG="{{ flavor }}"
    IMG="ghcr.io/{{ repo_organization }}/{{ variant }}:$TAG"
    NAME="gate-{{ variant }}-{{ flavor }}-$(date +%H%M%S)"
    case "{{ flavor }}" in
        kde*) DM=sddm ;; niri*|cosmic*) DM=greetd ;; xfce*) DM=lightdm ;; *) DM=gdm ;;
    esac
    cleanup() { corral delete "$NAME" >/dev/null 2>&1 || true; }
    trap cleanup EXIT
    corral create "$NAME" --bootc "$IMG" --disk 32Gi --wait-ssh --timeout 1200
    check() { corral ssh "$NAME" -u root -c "$1"; }
    RC=0
    [[ "$(check 'systemctl is-active graphical.target' | tr -d '[:space:]')" == active ]] || { echo "FAIL graphical.target"; RC=1; }
    [[ "$(check "systemctl is-active $DM" | tr -d '[:space:]')" == active ]] || { echo "FAIL $DM"; RC=1; }
    check 'systemctl --failed --no-legend' || true
    check 'bootc status --format json' | jq -r '.status.booted.image.image.image' || true
    [[ $RC -eq 0 ]] && echo "✅ boot-gate PASS: $IMG" || echo "❌ boot-gate FAIL: $IMG"
    exit $RC

# Boot-verify a qcow2/raw disk image with the same QEMU gate CI uses
# (serial boot marker or screenshot sanity; no Lima required)
verify-disk disk_image timeout='600':
    #!/usr/bin/env bash
    set -euo pipefail
    sudo ./scripts/iso-e2e.sh "{{ disk_image }}" --disk --output verify-out --timeout "{{ timeout }}"

# Verify an ISO using Lima
verify-iso iso_file:
    #!/usr/bin/env bash
    set -euo pipefail
    ./scripts/verify-iso.sh "{{ iso_file }}"

# Boot an ISO and expose the Anaconda WebUI on http://localhost:19090

# Optional: pass --kickstart <ks_file> for unattended install
install-test iso_file kickstart='':
    #!/usr/bin/env bash
    set -euo pipefail
    ks_arg=""
    [[ -n "{{ kickstart }}" ]] && ks_arg="--kickstart {{ kickstart }}"
    # shellcheck disable=SC2086
    bash ./scripts/install-test.sh "{{ iso_file }}" $ks_arg

# Internal helper to run a VM using the QEMU container
[private]
_run-vm type variant flavor='gnome' iso_file='':
    #!/usr/bin/env bash
    set -eoux pipefail

    if [[ -n "{{ iso_file }}" ]]; then
        image_file="{{ iso_file }}"
    elif [[ "{{ type }}" == "iso" ]]; then
        ISO_FILE=$(find . -maxdepth 1 -name "{{ variant }}-{{ flavor }}-*.iso" | head -1)
        if [[ -f "$ISO_FILE" ]]; then image_file="$ISO_FILE"; else image_file="{{ variant }}.iso"; fi
    else
        if [[ -f "{{ variant }}-{{ flavor }}.qcow2" ]]; then image_file="{{ variant }}-{{ flavor }}.qcow2"
        else image_file="{{ variant }}.qcow2"; fi
    fi

    if [[ ! -f "${image_file}" ]]; then
        if [[ -n "{{ iso_file }}" ]]; then echo "ISO not found: {{ iso_file }}"; exit 1; fi
        echo "Image ${image_file} not found. Building it now..."
        {{ just }} "{{ type }}" "{{ variant }}" "{{ flavor }}"
        if [[ ! -f "${image_file}" ]]; then
            if [[ "{{ type }}" == "qcow2" ]]; then image_file="{{ variant }}.qcow2"
            elif [[ "{{ type }}" == "iso" ]]; then image_file="{{ variant }}.iso"; fi
        fi
    fi

    port=8100
    while ss -tln | grep -q ":${port} "; do port=$(( port + 1 )); done
    echo "Using Web Port: ${port}"
    echo "Connect via Web: http://127.0.0.1:${port}"

    run_args=(--rm --privileged --pull=newer --publish "0.0.0.0:${port}:8006" --env "CPU_CORES=4" --env "RAM_SIZE=4G" --env "DISK_SIZE=64G" --env "TPM=Y" --env "GPU=Y" --device=/dev/kvm)

    ssh_port=$(( port + 1 ))
    while ss -tln | grep -q ":${ssh_port} "; do ssh_port=$(( ssh_port + 1 )); done
    echo "Using SSH Port: ${ssh_port}"
    echo "Connect via SSH: ssh centos@127.0.0.1 -p ${ssh_port}"
    run_args+=(--publish "0.0.0.0:${ssh_port}:22" --env "USER_PORTS=22" --env "NETWORK=user")

    QEMU_IMAGE="$(source scripts/_registry.sh 2>/dev/null && registry_ref qemu || echo 'ghcr.io/qemus/qemu')"
    run_args+=(--volume "${PWD}/${image_file}":"/boot.{{ type }}" "${QEMU_IMAGE}")

    (sleep 5 && xdg-open "http://127.0.0.1:${port}") &
    podman run "${run_args[@]}"

# ==============================================================================
#  DEV LOOP (same checks CI runs)
# ==============================================================================

# Shellcheck every script with the same excludes as lint.yml
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> shellcheck"
    /usr/bin/find . \
      -not -path './system_files/usr/share/gnome-shell/extensions/*' \
      -not -path './packages-repo/*' \
      -not -path './.build/*' \
      -not -path './_upstream-snapshots/*' \
      -not -path './.git/*' \
      -iname "*.sh" -type f \
      -exec shellcheck --exclude=SC1091,SC2114 {} +
    if command -v yamllint &>/dev/null; then
        echo "==> yamllint"
        yamllint -d relaxed .github/
    else
        echo "(yamllint not installed; skipped)"
    fi

# Run the full staged build pipeline
pipeline variant='all' flavor='all' tag='latest' dry_run='0':
    #!/usr/bin/env bash
    export JUST="{{ just }}"
    ./scripts/pipeline.sh "{{ variant }}" "{{ flavor }}" "{{ tag }}" "{{ dry_run }}"

# Attach to the currently running Zellij pipeline session
attach:
    #!/usr/bin/env bash
    SESSION=$(zellij list-sessions 2>/dev/null | grep "pipeline-" | head -1 | awk '{print $1}')
    [[ -z "$SESSION" ]] && SESSION=$(zellij list-sessions 2>/dev/null | grep -v "gemini-" | head -1 | awk '{print $1}')
    if [ -n "$SESSION" ]; then echo "Attaching to Zellij session: $SESSION"; zellij attach "$SESSION"
    else echo "No active zellij session found."; exit 1; fi
