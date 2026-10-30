# --- CI recipes called from workflows: sweeps ---
# Each recipe is a workflow step moved out of YAML so it can be run and tested locally.
# Recipe names are prefixed ci- (just imports share one flat namespace).

# Boot the QCOW2 built in the checkout under headless QEMU, wait for the desktop, and capture screenshot.png (weekly-qcow2-screenshots.yml)
ci-qcow2-boot-screenshot:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    # shellcheck source=scripts/lib/ci-scope.sh
    . {{ justfile_directory() }}/scripts/lib/ci-scope.sh

    QCOW2=$(find . -maxdepth 1 -name "*.qcow2" | head -1)
    echo "==> Booting $QCOW2 in QEMU (headless, KVM)..."

    OVMF_CODE=""
    for f in \
      /usr/share/OVMF/OVMF_CODE_4M.fd \
      /usr/share/OVMF/OVMF_CODE.fd \
      /usr/share/edk2/ovmf/OVMF_CODE.fd; do
      [ -f "$f" ] && OVMF_CODE="$f" && break
    done
    OVMF_VARS=""
    for f in \
      /usr/share/OVMF/OVMF_VARS_4M.fd \
      /usr/share/OVMF/OVMF_VARS.fd \
      /usr/share/edk2/ovmf/OVMF_VARS.fd; do
      if [ -f "$f" ]; then
        cp "$f" /tmp/OVMF_VARS.fd
        OVMF_VARS="/tmp/OVMF_VARS.fd"
        break
      fi
    done

    PFLASH=()
    if [ -n "$OVMF_CODE" ] && [ -n "$OVMF_VARS" ]; then
      echo "==> Using UEFI: $OVMF_CODE"
      PFLASH+=(-drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE")
      PFLASH+=(-drive "if=pflash,format=raw,file=$OVMF_VARS")
    else
      echo "==> OVMF not found, booting in BIOS mode"
    fi

    # Registered before launch so `just ci-cleanup` stops the VM if a later
    # step times out; the quit below still ends it on the normal path.
    QEMU_PIDFILE=/tmp/qemu-qcow2-screenshot.pid
    ci_own_pidfile "$QEMU_PIDFILE"

    sudo qemu-system-x86_64 \
      -smbios type=1,product=tunaos-countme-disabled \
      -machine type=q35,accel=kvm \
      -cpu host \
      -m 4G \
      -smp 2 \
      -drive "file=${QCOW2},format=qcow2,if=virtio" \
      "${PFLASH[@]}" \
      -monitor unix:/tmp/qemu-monitor.sock,server,nowait \
      -serial file:/tmp/serial.log \
      -pidfile "$QEMU_PIDFILE" \
      -display none \
      -daemonize

    for i in $(seq 1 30); do
      [ -S /tmp/qemu-monitor.sock ] && break
      sleep 2
    done

    echo "==> Waiting 4 minutes for desktop to load..."
    sleep 240

    echo "screendump /tmp/screenshot.ppm" | \
      sudo socat - UNIX-CONNECT:/tmp/qemu-monitor.sock
    sleep 3

    if sudo test -f /tmp/screenshot.ppm; then
      sudo convert /tmp/screenshot.ppm screenshot.png 2>/dev/null || \
        sudo cp /tmp/screenshot.ppm screenshot.png
      echo "==> Screenshot captured: $(ls -lh screenshot.png)"
    else
      echo "WARNING: screenshot.ppm not found; serial log follows:"
      sudo cat /tmp/serial.log || true
    fi

    echo "quit" | sudo socat - UNIX-CONNECT:/tmp/qemu-monitor.sock || true

# Boot the live ISO for VARIANT/FLAVOR via iso-e2e.sh, screendump the settled desktop to screenshot.png and set captured=true in GITHUB_OUTPUT (weekly-desktop-screenshots.yml)
ci-desktop-screenshot variant flavor:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}

    ISO=$(find . -maxdepth 1 -name "{{ variant }}-{{ flavor }}-*.iso" | head -1)
    if [[ -z "$ISO" ]]; then
      echo "::error::No ISO found for {{ variant }}-{{ flavor }}"
      exit 1
    fi
    KVM_FLAG=""
    [[ -r /dev/kvm && -w /dev/kvm ]] || KVM_FLAG="--no-kvm"

    # Boot to the live-ready marker, then keep the VM up so the desktop
    # can finish painting before we grab the screenshot. The CI scope
    # variables are preserved so iso-e2e.sh registers its QEMU/swtpm
    # pidfiles for `just ci-cleanup`.
    set +e
    sudo --preserve-env=KVM_FLAG,GITHUB_RUN_ID,GITHUB_RUN_ATTEMPT,GITHUB_JOB,CI_SCOPE_SUFFIX,RUNNER_TEMP,GITHUB_WORKSPACE \
      ./scripts/iso-e2e.sh "$ISO" \
      --output shot-out --timeout 600 --keep-vm $KVM_FLAG
    rc=$?
    set -e
    echo "iso-e2e rc=$rc"

    # Let the compositor settle, then screendump the live desktop.
    if [[ -S shot-out/monitor.sock ]]; then
      sleep 45
      echo "screendump $(pwd)/shot-out/desktop.ppm" | \
        sudo socat - "UNIX-CONNECT:shot-out/monitor.sock" || true
      sleep 3
      echo "system_powerdown" | \
        sudo socat - "UNIX-CONNECT:shot-out/monitor.sock" || true
    fi

    # Prefer the settled desktop shot; fall back to iso-e2e's ready shot.
    SRC=""
    for cand in shot-out/desktop.ppm shot-out/10-ready.ppm shot-out/00-boot.ppm; do
      if sudo test -f "$cand"; then SRC="$cand"; break; fi
    done
    if [[ -z "$SRC" ]]; then
      echo "::warning::No screenshot captured for {{ variant }}-{{ flavor }}"
      exit 0
    fi
    sudo convert "$SRC" screenshot.png 2>/dev/null || sudo cp "$SRC" screenshot.png
    sudo chown "$(id -u):$(id -g)" screenshot.png || true
    echo "captured=true" >> "$GITHUB_OUTPUT"
    echo "==> Captured $(ls -lh screenshot.png) from $SRC"
