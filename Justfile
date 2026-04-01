export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export default_tag := env("DEFAULT_TAG", "latest")
export common_image := env("COMMON_IMAGE", "ghcr.io/projectbluefin/common")
export brew_image := env("BREW_IMAGE", "ghcr.io/ublue-os/brew")
export coreos_stable_version := env("COREOS_STABLE_VERSION", "43")
just := just_executable()
arch := arch()
yq := `which yq`
export platform := env("PLATFORM", if arch == "x86_64" { if `rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; echo $?` == "0" { "linux/amd64/v2" } else { "linux/amd64" } } else if arch == "arm64" { "linux/arm64" } else if arch == "aarch64" { "linux/arm64" } else { error("Unsupported ARCH '" + arch + "'. Supported values are 'x86_64', 'aarch64', and 'arm64'.") })

# --- Default Base Image (for 'base' flavor builds) ---

export base_image := env("BASE_IMAGE", "quay.io/almalinuxorg/almalinux-bootc")
export base_image_tag := env("BASE_IMAGE_TAG", "10")

# Simulate the GitHub Actions CI matrix
simulate-matrix:
    #!/usr/bin/env bash
    ./scripts/simulate-matrix.sh

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
    /usr/bin/find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -iname "*.sh" -type f -exec shellcheck --exclude=SC1091 "{}" ";"
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.yaml" | while read -r file; do
        yamllint -c ./.yamllint.yml "$file" || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.yml" | while read -r file; do
        yamllint "$file" || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.json" | while read -r file; do
        jq . "$file" > /dev/null || { exit 1; }
    done
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.just" | while read -r file; do
        just --unstable --fmt --check -f $file
    done
    if command -v actionlint &> /dev/null; then
        actionlint -ignore "permission \"id-token\" is unknown" \
                   -ignore "SC2086" -ignore "SC2129" -ignore "SC2001" \
                   -ignore "SC2034" -ignore "SC2015" -ignore "SC1001" \
                   -ignore "SC2295" -ignore "SC2016" \
                   -ignore "save-always" \
                   -ignore "cannot be filtered" \
                   .github/workflows/*.yml .github/workflows/*.yaml || { exit 1; }
    fi
    just --unstable --fmt --check -f Justfile

# Generate GitHub Actions workflows from build-config.yml
generate-workflows:
    #!/usr/bin/env bash
    chmod +x scripts/generate-workflows.py
    python3 scripts/generate-workflows.py

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
    rm -f out.ociarchive
    echo "Removing local podman images for all variants and flavors..."
    readarray -t VARIANTS < <({{ yq }} -r '.variants[].id' .github/build-config.yml 2>/dev/null || echo -e "yellowfin\nalbacore\nbonito\nskipjack\nredfin")
    for variant in "${VARIANTS[@]}"; do
        readarray -t FLAVORS < <({{ yq }} -r ".variants[] | select(.id == \"$variant\") | .flavors[].id" .github/build-config.yml 2>/dev/null || true)
        for flavor in "${FLAVORS[@]}"; do
            podman rmi -f "localhost/${variant}:${flavor}" 2>/dev/null || true
            sudo podman rmi -f "localhost/${variant}:${flavor}" 2>/dev/null || true
        done
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

    # Pass RHSM credentials
    BUILD_ARGS+=("--build-arg" "RHSM_USER=${RHSM_USER:-}")
    BUILD_ARGS+=("--build-arg" "RHSM_PASSWORD=${RHSM_PASSWORD:-}")
    BUILD_ARGS+=("--build-arg" "RHSM_ORG=${RHSM_ORG:-}")
    BUILD_ARGS+=("--build-arg" "RHSM_ACTIVATION_KEY=${RHSM_ACTIVATION_KEY:-}")

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

    # Use a clean temp dir to avoid SELinux relabeling issues with existing files in PWD
    CHUNK_OUT=$(mktemp -d)
    # Pass 2: Run chunkah externally against the built image
    podman run --rm \
        --security-opt label=disable \
        --dns=8.8.8.8 \
        --entrypoint="" \
        -v "${CHUNK_OUT}:/run/out:Z" \
        --mount "type=image,source=${PRE_CHUNK_TAG},target=/chunkah" \
        ghcr.io/tuna-os/chunkah:latest \
        sh -c 'chunkah build > /run/out/out.ociarchive'
    mv "${CHUNK_OUT}/out.ociarchive" out.ociarchive
    rm -rf "${CHUNK_OUT}"

    echo "==> Applying labels from OCI archive..."

    # Pass 3: Load archive into podman storage via podman load, then apply OCI labels.
    # podman load guarantees the same graphRoot as the subsequent podman build.
    # skopeo copy is avoided here because CI uses ublue-os/container-storage-action
    # which mounts a BTRFS graphRoot for podman; skopeo defaults to overlay and writes
    # to a different path, causing podman build to fall back to a remote registry pull.

    # Remove the pre-chunk image before loading the rechunked archive to free disk space.
    # GDX images are 5-6 GB; keeping both in storage simultaneously causes disk pressure
    # on S3 CI runners, which triggers a podman storage index bug where podman load
    # copies the config blob but fails to register it ("image not known").
    podman rmi "${PRE_CHUNK_TAG}" 2>/dev/null || true

    RECHUNKED_REF="localhost/{{ target_tag_with_version }}-rechunked-$$"
    LOADED_ID=$(podman load --input out.ociarchive | awk '/Loaded image/{print $NF}')
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

    # Cleanup
    rm -f out.ociarchive

# Build a TunaOS variant
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

# Build the custom image-builder-dev container needed for live ISO generation.
build-image-builder:
    #!/usr/bin/env bash
    set -euo pipefail
    if sudo podman image exists image-builder-dev; then
        echo "image-builder-dev already exists. To rebuild: sudo podman rmi image-builder-dev"
        exit 0
    fi
    sudo bash ./scripts/build-live-iso.sh --build-image-builder-only

# Build a TunaOS live installer ISO using the bootc-isos approach.
live-iso variant='skipjack' flavor='gnome' repo='local' tag='' dev='0':
    #!/usr/bin/env bash
    set -euo pipefail
    _tag="{{ tag }}"
    [[ -z "$_tag" ]] && _tag="{{ flavor }}"
    sudo DEV_SSHD="{{ dev }}" bash ./scripts/build-live-iso.sh "{{ variant }}" "{{ flavor }}" "{{ repo }}" "$_tag"

# Shortcut for live-iso
iso variant='skipjack' flavor='gnome' repo='local' tag='' dev='0':
    @{{ just }} live-iso {{ variant }} {{ flavor }} {{ repo }} {{ tag }} {{ dev }}

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
    if [[ "${IMG_REF}" == localhost/* ]] || [[ "${IMG_REF}" == *"/"* && "${IMG_REF}" != ghcr* ]]; then
        echo "==> Syncing $IMG_REF into root podman storage..."
        podman save "$IMG_REF" | sudo podman load
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

    # ghcr.io/novnc/novnc ships novnc_proxy (websockify wrapper + static files).
    # --network host lets the container reach Lima's VNC on 127.0.0.1.
    podman run -d --rm \
        --name "${VM_NAME}-novnc" \
        --network host \
        ghcr.io/novnc/novnc:latest \
        /usr/share/novnc/utils/novnc_proxy \
            --listen "${NOVNC_PORT}" \
            --vnc "${VNC_HOST}:${VNC_PORT}"

    # Build the local URL; embed password so the browser connects automatically
    NOVNC_PARAMS="vnc.html?autoconnect=1"
    [[ -n "${VNC_PASS}" ]] && NOVNC_PARAMS="${NOVNC_PARAMS}&password=${VNC_PASS}"
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

    run_args+=(--volume "${PWD}/${image_file}":"/boot.{{ type }}" ghcr.io/qemus/qemu)

    (sleep 5 && xdg-open "http://127.0.0.1:${port}") &
    podman run "${run_args[@]}"

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
