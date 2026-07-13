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

# Private build engine — thin wrapper that exports env vars and calls the script.
[private]
_build target_tag_with_version target_tag container_file base_image_for_build target_platform use_cache enable_gdx enable_hwe desktop_flavor is_ci_build enable_sshd_build *args: _ensure-deps
    #!/usr/bin/env bash
    set -euxo pipefail
    export IMAGE_TAG="{{ target_tag_with_version }}"
    export VARIANT="{{ target_tag }}"
    export CONTAINERFILE="{{ container_file }}"
    export BASE_IMAGE="{{ base_image_for_build }}"
    export PLATFORM="{{ target_platform }}"
    export USE_CACHE="{{ use_cache }}"
    export ENABLE_NVIDIA="{{ enable_gdx }}"
    export ENABLE_HWE="{{ enable_hwe }}"
    export DESKTOP_FLAVOR="{{ desktop_flavor }}"
    export IS_CI="{{ is_ci_build }}"
    export ENABLE_SSHD="{{ enable_sshd_build }}"
    export IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io}"
    export REPO_ORGANIZATION="{{ repo_organization }}"
    export COMMON_IMAGE="{{ common_image }}"
    export BREW_IMAGE="{{ brew_image }}"
    export COREOS_STABLE_VERSION="{{ coreos_stable_version }}"
    export YQ="{{ yq }}"
    # OVERLAY_TYPE inherited from parent shell (exported by build recipe)
    ./scripts/build-image-inner.sh

# Build a custom TunaOS overlay using the configuration in custom/
build-custom base="" tag="": _ensure-deps
    #!/usr/bin/env bash
    set -euo pipefail
    BASE_IMAGE="{{ base }}"
    if [[ -z "${BASE_IMAGE}" ]]; then
        BASE_IMAGE=$(python3 -c "import re; open_f = open('custom/image.yaml').read(); print(re.search(r'base:\s*(\S+)', open_f).group(1))" 2>/dev/null || echo "ghcr.io/tuna-os/yellowfin:gnome")
    fi
    TARGET_TAG="{{ tag }}"
    if [[ -z "${TARGET_TAG}" ]]; then
        TARGET_TAG=$(python3 -c "import re; open_f = open('custom/image.yaml').read(); print(re.search(r'tag:\s*(\S+)', open_f).group(1))" 2>/dev/null || echo "my-custom-os")
    fi
    echo "==> Building custom image based on ${BASE_IMAGE} as localhost/${TARGET_TAG}..."
    podman build \
        --file Containerfile.custom \
        --build-arg BASE_IMAGE="${BASE_IMAGE}" \
        --tag "localhost/${TARGET_TAG}" \
        .

# Build QCOW2 from custom TunaOS image
run-custom-vm tag="":
    #!/usr/bin/env bash
    set -euo pipefail
    TARGET_TAG="{{ tag }}"
    if [[ -z "${TARGET_TAG}" ]]; then
        TARGET_TAG=$(python3 -c "import re; open_f = open('custom/image.yaml').read(); print(re.search(r'tag:\s*(\S+)', open_f).group(1))" 2>/dev/null || echo "my-custom-os")
    fi
    # Use scripts/build-qcow2.sh to build the QCOW2 from local image
    ./scripts/build-qcow2.sh "localhost/${TARGET_TAG}"

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
    ENABLE_SSHD="{{ enable_sshd_var }}"
    FLAVOR="{{ flavor }}"

    if [[ "${FLAVOR}" == "all" ]]; then
        readarray -t FLAVORS < <({{ yq }} -r '.variants[] | select(.id == "{{ variant }}") | .flavors[].id' .github/build-config.yml)
        for f in "${FLAVORS[@]}"; do {{ just }} build "{{ variant }}" "$f"; done
        exit 0
    fi

    # Resolve flavor into build parameters via external script (testable, DRY)
    eval "$(./scripts/resolve-flavor.sh "{{ variant }}" "${FLAVOR}" "{{ is_ci }}")"
    # CONTAINERFILE, DESKTOP_FLAVOR, ENABLE_HWE, ENABLE_NVIDIA, OVERLAY_TYPE, PARENT_FLAVOR now set
    export OVERLAY_TYPE

    # Resolve BASE_FOR_BUILD based on PARENT_FLAVOR
    if [[ -z "${PARENT_FLAVOR}" ]]; then
        BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}")
    elif [[ "{{ is_ci }}" = "1" ]]; then
        # CI chains on the -testing stream tag
        BASE_FOR_BUILD="ghcr.io/{{ repo_organization }}/{{ variant }}:${PARENT_FLAVOR}-testing"
    else
        BASE_FOR_BUILD="localhost/{{ variant }}:${PARENT_FLAVOR}"
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

# Full lifecycle test: build → ISO → boot → install → verify (nested QEMU on corral VM)
# Usage: just lifecycle-test redfin gnome
# just lifecycle-test albacore kde
lifecycle-test variant='albacore' flavor='gnome':
    ./scripts/lifecycle-test.sh "{{ variant }}" "{{ flavor }}"

# Build on a corral VM (fans out the full flavor matrix on a KubeVirt builder)
# Usage: just corral-build redfin all
# just corral-build yellowfin gnome kde
corral-build variant='redfin' +flavors='all':
    ./scripts/corral-build.sh "{{ variant }}" {{ flavors }}

# Build a TunaOS live ISO via tacklebox (no Anaconda, tbox-live + sd-boot)
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

# EXPERIMENT: Build ONE combined DE-centric ISO spanning multiple variants.
# de: gnome | kde | cosmic | niri  (an id in de_iso_groups in build-config.yml)
# Produces tuna-<de>-<version>-<arch>.iso for size comparison with iso-group.
iso-de-group de='gnome' repo='ghcr':
    sudo bash ./scripts/build-iso-de-group.sh "{{ de }}" "{{ repo }}"
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
    [[ "$OUTPUT_NAME" == grouper* || "$OUTPUT_NAME" == sailfin* || "$OUTPUT_NAME" == guppy* || "$OUTPUT_NAME" == marlin* || "$OUTPUT_NAME" == flounder* ]] && COMPOSEFS_ARGS=(--composefs-backend)

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

# Boot-gate a published (or local) image via corral: builds a disk with
# bootc, boots it (KubeVirt when your kubeconfig reaches a cluster, local
# QEMU otherwise), waits for SSH, then runs the tier-1 desktop health checks.
# One command, same behavior locally and in CI. Set CORRAL_NODE to pin a node.
boot-gate variant flavor='gnome' tag='':
    #!/usr/bin/env bash
    set -euo pipefail
    REPO_ORGANIZATION="{{ repo_organization }}" ./scripts/boot-gate.sh "{{ variant }}" "{{ flavor }}" "{{ tag }}"

# Boot-gate a whole matrix of images in parallel across the KubeVirt cluster,
# spreading VMs across nodes with bounded concurrency. Pass variant:flavor
# pairs, or a variant alone to gate its default desktop set.
# Usage:
#   just boot-gate-matrix yellowfin:gnome yellowfin:kde albacore:gnome
# just boot-gate-matrix yellowfin              # gnome kde cosmic niri xfce
boot-gate-matrix +targets='yellowfin':
    ./scripts/boot-gate-matrix.sh {{ targets }}

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
