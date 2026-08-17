# --- QCOW2 disk-image build (bootc install to-disk, via loopback in a privileged container) ---
# Extracted from the root Justfile (#508: cross-repo Justfile inflation).
# repo_organization, just, and platform are root-level export/assignment and remain visible here
# (just's import shares one flat recipe/variable namespace).

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
    #
    # Two INDEPENDENT signals, probed from the image rather than guessed from
    # its name (the name-based heuristic is exactly what tuna-os/wootc had to
    # rip out — see payload/deployer/deploy.sh "the crux fix"):
    #
    #   BACKEND is probed from IMAGE CONTENT by probe_image_backend() in
    #     scripts/lib/common.sh — a faithful port of tuna-os/wootc
    #     deploy.sh:867-949. The variant name is not a signal and neither is
    #     the bootloader; see that function for the ordering rationale and for
    #     why the previous `! command -v bootupctl` test mis-classified marlin.
    #   SEALED → prepare-root.conf has [composefs] enabled: the rootfs is
    #     composefs-sealed and needs fs-verity, which XFS LACKS. On the xfs
    #     default from 00-tunaos.toml the initramfs fails initrd-switch-root
    #     and drops to dracut emergency mode — every composefs variant's
    #     desktop Gate timed out at "no graphical session" (confirmed on
    #     sailfin and grouper). ext4 is the proven sealed filesystem
    #     (wootc deploy.sh:809-821); btrfs also has fs-verity but its ostree
    #     deployment fails to mount (sysroot.mount timeout, wootc#35), so it
    #     is deliberately NOT used here.
    #
    # Sealed is what drives the filesystem, and it is independent of the
    # backend: traditional-ostree images can be sealed too.
    #
    # A probe that cannot run is FATAL, never a silent default. It used to
    # swallow stderr and fall back to BACKEND=ostree/SEALED=0, which is the
    # worst possible guess: on a sealed composefs image that drops
    # --composefs-backend and leaves the rootfs on xfs, and the resulting disk
    # boots straight into a dracut emergency shell with nothing in the log
    # explaining why. Exactly that happened on sailfin niri (run 30594521039):
    # a broken podman on the runner made the probe report ostree/unsealed for
    # an image its kde/xfce siblings probed as composefs-native/SEALED=1.
    PROBE_ERR=$(mktemp)
    if ! PROBE=$(. scripts/lib/common.sh && probe_image_backend "$IMG_REF" sudo podman 2>"$PROBE_ERR"); then
        echo "ERROR: could not probe $IMG_REF for its bootc backend:" >&2
        cat "$PROBE_ERR" >&2
        rm -f "$PROBE_ERR"
        exit 1
    fi
    rm -f "$PROBE_ERR"
    echo "==> image probe: $(echo "$PROBE" | tr '\n' ' ')"

    COMPOSEFS_ARGS=()
    grep -q '^BACKEND=composefs-native$' <<<"$PROBE" && COMPOSEFS_ARGS+=(--composefs-backend)
    grep -q '^SEALED=1$' <<<"$PROBE" && COMPOSEFS_ARGS+=(--filesystem ext4)

    # Console ORDER matters: the LAST console= is the primary /dev/console, and
    # that is where dracut/systemd (all userspace) writes. With tty0 last,
    # initramfs failures were visible only on the VGA screen (the Gate's
    # screenshot) while the captured serial.log held nothing but kernel printk —
    # an emergency-mode boot with no recorded reason. ttyS0 last puts the boot
    # log the Gate captures where it is actually useful.
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
            --karg console=tty0 --karg console=ttyS0 \
            --karg systemd.unit=graphical.target \
            "${SSH_KEY_ARGS[@]}" \
            --source-imgref "containers-storage:${IMG_REF}" \
            /disk.img

    [[ -n "$SSH_PUBKEYS_FILE" ]] && rm -f "$SSH_PUBKEYS_FILE"

    # bootc's composefs backend writes the ESP kernel/initrd out of the EROFS
    # store, which zero-fills files past its inline threshold — so the 70MB+
    # initramfs that lands on the ESP is NOT the one in the image. The boot then
    # runs a stale/garbled initrd: bootc-root-setup.service is absent from it, so
    # nothing consumes the composefs= karg, /sysroot is mounted but never
    # prepared, and initrd-switch-root fails into a dracut emergency shell.
    # Re-extract the real bytes over the ESP copies (same workaround corral's
    # KubeVirt builder applies, pkg/kubevirt/bootc.go).
    if grep -q '^BACKEND=composefs-native$' <<<"$PROBE"; then
        echo "==> composefs: re-extracting real kernel/initrd onto the ESP..."
        LOOP=$(sudo losetup --find --show --partscan "$RAW_ABS")
        ESP_MNT=$(mktemp -d)
        for P in 1 2 3; do
            if sudo mount "${LOOP}p${P}" "$ESP_MNT" 2>/dev/null; then
                [[ -d "$ESP_MNT/EFI" ]] && break
                sudo umount "$ESP_MNT"
            fi
        done
        UKI_DIR=$(sudo sh -c "ls -d '$ESP_MNT'/EFI/Linux/bootc_composefs-* 2>/dev/null" | head -1)
        if [[ -n "$UKI_DIR" ]]; then
            KDIR=$(mktemp -d)
            sudo podman run --rm --entrypoint="" -v "$KDIR:/out:z" "$IMG_REF" \
                sh -c 'KV=$(ls /usr/lib/modules | head -1); cp "/usr/lib/modules/$KV/vmlinuz" /out/vmlinuz; cp "/usr/lib/modules/$KV/initramfs.img" /out/initrd'
            sudo cp -f "$KDIR/vmlinuz" "$UKI_DIR/vmlinuz"
            sudo cp -f "$KDIR/initrd"  "$UKI_DIR/initrd"
            sudo sync
            echo "==> re-extracted kernel+initrd into $(basename "$UKI_DIR")"
            rm -rf "$KDIR"
        else
            echo "WARNING: no bootc_composefs-* UKI dir found on the ESP; skipping re-extract" >&2
        fi
        sudo umount "$ESP_MNT" 2>/dev/null || true
        rmdir "$ESP_MNT" 2>/dev/null || true
        sudo losetup -d "$LOOP" 2>/dev/null || true
    fi

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
