# just/iso.just — Image artifact generation (ISO, QCOW2)

# [iso]
# Build a TunaOS live ISO via tacklebox (no Anaconda, dmsquash-live + sd-boot)
live-iso variant='skipjack' flavor='gnome' repo='local' tag='':
    #!/usr/bin/env bash
    set -euo pipefail
    _tag="{{ tag }}"
    [[ -z "$_tag" ]] && _tag="{{ flavor }}"
    sudo bash ./scripts/build-iso-tacklebox.sh "{{ variant }}" "{{ flavor }}" "{{ repo }}" "$_tag"

# [iso]
# Shortcut for live-iso
iso variant='skipjack' flavor='gnome' repo='local' tag='':
    @{{ just }} live-iso {{ variant }} {{ flavor }} {{ repo }} {{ tag }}

# [iso]
# Build a live ISO via tacklebox (alias, replaces deprecated bootc-image-builder approach)
iso-tacklebox variant='yellowfin' flavor='gnome' repo='local' tag='':
    #!/usr/bin/env bash
    set -euo pipefail
    _tag="{{ tag }}"
    [[ -z "$_tag" ]] && _tag="{{ flavor }}"
    sudo bash ./scripts/build-iso-tacklebox.sh "{{ variant }}" "{{ flavor }}" "{{ repo }}" "$_tag"

# [iso]
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
