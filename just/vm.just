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
    bash ./scripts/_lima-novnc.sh "{{ vm_name }}" "{{ type }}" "{{ image_path }}"

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
