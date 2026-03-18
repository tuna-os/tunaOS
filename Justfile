export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export default_tag := env("DEFAULT_TAG", "latest")
export common_image := env("COMMON_IMAGE", "ghcr.io/projectbluefin/common")
export brew_image := env("BREW_IMAGE", "ghcr.io/ublue-os/brew")
export coreos_stable_version := env("COREOS_STABLE_VERSION", "43")
just := just_executable()
arch := arch()
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
    readarray -t VARIANTS < <(yq -r '.variants[].id' .github/build-config.yml 2>/dev/null || echo -e "yellowfin\nalbacore\nbonito\nskipjack\nredfin")
    for variant in "${VARIANTS[@]}"; do
        readarray -t FLAVORS < <(yq -r ".variants[] | select(.id == \"$variant\") | .flavors[].id" .github/build-config.yml 2>/dev/null || true)
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
    if ! command -v yq &> /dev/null; then
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
    BUILD_ARGS+=("--build-arg" "ENABLE_HWE={{ enable_hwe }}")
    BUILD_ARGS+=("--build-arg" "ENABLE_GDX={{ enable_gdx }}")
    BUILD_ARGS+=("--build-arg" "DESKTOP_FLAVOR={{ desktop_flavor }}")

    AKMODS_ORG=$(yq -r ".variants[] | select(.id == \"{{ target_tag }}\") | .akmods // \"ublue-os\"" .github/build-config.yml)
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

    echo "==> Build-time chunking enabled. Starting two-pass build..."

    # Pass 1: Build up to 'chunker' stage and extract the OCI archive to host
    # We must use --skip-unused-stages=false to ensure the 'builder' stage is actually built
    # and available for the 'chunker' mount.
    podman build \
        --security-opt label=disable \
        --dns=8.8.8.8 \
        --platform "{{ target_platform }}" \
        --target="chunker" \
        "${BUILD_ARGS[@]}" \
        --skip-unused-stages=false \
        -v "$(pwd):/run/out:Z" \
        {{ args }} \
        --pull=newer \
        --file "{{ container_file }}" \
        .

    echo "==> OCI archive generated. Starting Pass 2 (final stage)..."

    # Pass 2: Build the 'final' stage from the generated archive
    podman build \
        --security-opt label=disable \
        --dns=8.8.8.8 \
        --platform "{{ target_platform }}" \
        --target="final" \
        "${BUILD_ARGS[@]}" \
        --tag "{{ target_tag_with_version }}" \
        --file "{{ container_file }}" \
        .

    # Clean up the large archive
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
            PLATFORM=$(yq -r ".variants[] | select(.id == \"{{ variant }}\") | .platforms | join(\",\")" .github/build-config.yml)
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
        readarray -t FLAVORS < <(yq -r '.variants[] | select(.id == "{{ variant }}") | .flavors[].id' .github/build-config.yml)
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

# Generate a QCOW2 disk image using bcvk (bootc virtualization kit)
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
    echo "==> Generating $OUTPUT from $IMG_REF using bcvk..."

    if ! command -v bcvk &>/dev/null; then
        echo "Error: 'bcvk' not found. Please install it (cargo install --git https://github.com/bootc-dev/bcvk.git bcvk)"
        exit 1
    fi

    sudo "$(which bcvk)" to-disk --format=qcow2 "$IMG_REF" "$OUTPUT"
    sudo chown "${SUDO_UID:-$(id -u)}:${SUDO_GID:-$(id -g)}" "$OUTPUT"
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

    port=8006
    while ss -tln | grep -q ":${port} "; do port=$(( port + 1 )); done
    echo "Using Web Port: ${port}"
    echo "Connect via Web: http://127.0.0.1:${port}"

    run_args=(--rm --privileged --pull=newer --publish "127.0.0.1:${port}:8006" --env "CPU_CORES=4" --env "RAM_SIZE=4G" --env "DISK_SIZE=64G" --env "TPM=Y" --env "GPU=Y" --device=/dev/kvm)

    ssh_port=$(( port + 1 ))
    while ss -tln | grep -q ":${ssh_port} "; do ssh_port=$(( ssh_port + 1 )); done
    echo "Using SSH Port: ${ssh_port}"
    echo "Connect via SSH: ssh centos@127.0.0.1 -p ${ssh_port}"
    run_args+=(--publish "127.0.0.1:${ssh_port}:22" --env "USER_PORTS=22" --env "NETWORK=user")

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
