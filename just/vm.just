# just/vm.just — Testing and VM infrastructure

# [vm]
# Test an image locally using Lima VM (automated display manager check)
test-vm variant flavor='gnome':
    #!/usr/bin/env bash
    set -euo pipefail
    bash ./scripts/test-vm.sh {{ variant }} {{ flavor }}

# [vm]
# Boot an image in QEMU via browser (uses ghcr.io/qemus/qemu)
run-qcow2 variant flavor='gnome':
    @{{ just }} _run-vm qcow2 {{ variant }} {{ flavor }}

# [vm]
# Boot an ISO in QEMU via browser
run-iso variant flavor='gnome' iso_file='':
    @{{ just }} _run-vm iso {{ variant }} {{ flavor }} "{{ iso_file }}"

# [vm]
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

# [vm]
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

# [vm]
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

# [vm]
# Verify an image using Lima (automated DM check)
verify variant flavor='gnome':
    #!/usr/bin/env bash
    set -euo pipefail
    ./scripts/verify-image.sh "{{ variant }}" "{{ flavor }}"

# [vm]
# Verify an ISO using Lima
verify-iso iso_file:
    #!/usr/bin/env bash
    set -euo pipefail
    ./scripts/verify-iso.sh "{{ iso_file }}"

# [vm]
# Boot an ISO and expose the Anaconda WebUI on http://localhost:19090
# Optional: pass --kickstart <ks_file> for unattended install
install-test iso_file kickstart='':
    #!/usr/bin/env bash
    set -euo pipefail
    ks_arg=""
    [[ -n "{{ kickstart }}" ]] && ks_arg="--kickstart {{ kickstart }}"
    # shellcheck disable=SC2086
    bash ./scripts/install-test.sh "{{ iso_file }}" $ks_arg

# [vm]
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
