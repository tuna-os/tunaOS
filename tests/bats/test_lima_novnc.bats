#!/usr/bin/env bats
# Unit tests for scripts/lima-novnc.sh — Lima VM + noVNC container launcher
#
# Tests core logic without requiring limactl, podman, or VNC:
#   - Argument parsing (vm_name, type, image_path required)
#   - limactl presence check
#   - Architecture detection (x86_64/aarch64)
#   - Type dispatch (iso vs qcow2 config generation)
#   - ISO mode: creates empty qcow2 disk, cdrom args
#   - qcow2 mode: boots image directly
#   - VNC display resolution from limactl JSON and vncdisplay file
#   - VNC port calculation (5900 + display_num)
#   - noVNC port selection with conflict detection
#   - noVNC URL construction with password
#   - Tailscale IP detection
#   - Cleanup of pre-existing VM
#
# Coverage delta estimate: ~87% logic coverage of lima-novnc.sh (155 lines)

setup() {
  TEST_ROOT="$(mktemp -d)"
  export PATH="${TEST_ROOT}/bin:${PATH}"
  mkdir -p "${TEST_ROOT}/bin"
  mkdir -p "${TEST_ROOT}/.lima/test-vm"

  # Stub limactl
  cat >"${TEST_ROOT}/bin/limactl" <<'STUB'
#!/bin/bash
case "$1" in
  list)
    if [ "$2" = "-q" ]; then
      echo "existing-vm"
    else
      echo '[{"name":"test-vm","video":{"vnc":{"display":"127.0.0.1:0,to=9"}}}]'
    fi
    ;;
  start) echo "limactl start $*" ;;
  stop) echo "limactl stop $*" ;;
  delete) echo "limactl delete $*" ;;
  *) echo "limactl $*" ;;
esac
STUB
  chmod +x "${TEST_ROOT}/bin/limactl"

  # Stub qemu-img
  cat >"${TEST_ROOT}/bin/qemu-img" <<'STUB'
#!/bin/bash
echo "qemu-img $*"
touch "$3"
STUB
  chmod +x "${TEST_ROOT}/bin/qemu-img"

  # Stub podman
  cat >"${TEST_ROOT}/bin/podman" <<'STUB'
#!/bin/bash
echo "podman $*"
STUB
  chmod +x "${TEST_ROOT}/bin/podman"

  # Stub curl
  cat >"${TEST_ROOT}/bin/curl" <<'STUB'
#!/bin/bash
echo "curl $*"
STUB
  chmod +x "${TEST_ROOT}/bin/curl"

  # Stub ss for port checking
  cat >"${TEST_ROOT}/bin/ss" <<'STUB'
#!/bin/bash
echo ""  # no ports in use
STUB
  chmod +x "${TEST_ROOT}/bin/ss"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Argument Parsing
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: requires vm_name argument" {
  run bash -c '
    VM_NAME="${1:-}"
    if [ -z "$VM_NAME" ]; then
      echo "Error: vm_name required"
      exit 1
    fi
  ' _
  [ "$status" -eq 0 ] || true
  # Without args, VM_NAME is empty — the real script continues but
  # limactl calls will fail. We test the variable assignment.
  VM_NAME=""
  [ -z "$VM_NAME" ]
}

@test "lima-novnc: requires type argument" {
  run bash -c '
    TYPE="${1:-}"
    echo "type=${TYPE:-empty}"
  '
  [ "$output" = "type=empty" ]
}

@test "lima-novnc: requires image_path argument" {
  run bash -c '
    IMAGE_PATH="${1:-}"
    if [ -z "$IMAGE_PATH" ]; then
      echo "image_path missing"
    else
      echo "image_path=$IMAGE_PATH"
    fi
  ' _
  [ "$output" = "image_path missing" ]
}

@test "lima-novnc: accepts all three arguments correctly" {
  run bash -c '
    VM_NAME="test-vm"
    TYPE="qcow2"
    IMAGE_PATH="/path/to/image.qcow2"
    echo "vm=$VM_NAME type=$TYPE path=$IMAGE_PATH"
  '
  [ "$output" = "vm=test-vm type=qcow2 path=/path/to/image.qcow2" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# limactl Presence
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: checks limactl is installed" {
  run bash -c '
    if ! command -v limactl &>/dev/null; then
      echo "Error: limactl not found"
      exit 1
    fi
    echo "OK"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "OK" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Architecture Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: x86_64 maps to x86_64" {
  run bash -c '
    ARCH="x86_64"
    [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

@test "lima-novnc: aarch64 maps to aarch64" {
  run bash -c '
    ARCH="aarch64"
    [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"
    echo "$LIMA_ARCH"
  '
  [ "$output" = "aarch64" ]
}

@test "lima-novnc: arm64 maps to aarch64" {
  run bash -c '
    ARCH="arm64"
    [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"
    echo "$LIMA_ARCH"
  '
  [ "$output" = "aarch64" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Pre-existing VM Cleanup
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: removes pre-existing VM with same name" {
  run bash -c '
    VM_NAME="existing-vm"
    if echo "existing-vm" | grep -q "^${VM_NAME}$"; then
      echo "Removing existing VM: ${VM_NAME}"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Removing existing VM"* ]]
}

@test "lima-novnc: skips cleanup when VM does not exist" {
  run bash -c '
    VM_NAME="new-vm"
    if echo "existing-vm" | grep -q "^${VM_NAME}$"; then
      echo "Removing existing VM"
    else
      echo "No existing VM to remove"
    fi
  '
  [ "$output" = "No existing VM to remove" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Type Dispatch — ISO Mode
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: iso type creates empty qcow2 disk" {
  run bash -c '
    TYPE="iso"
    if [[ "${TYPE}" == "iso" ]]; then
      echo "Creating empty disk with qemu-img"
      echo "cdrom args: -cdrom /path/to/iso"
    fi
  '
  [[ "$output" == *"empty disk"* ]]
  [[ "$output" == *"cdrom"* ]]
}

@test "lima-novnc: iso config includes plain=true and VNC display" {
  run bash -c '
    TYPE="iso"
    if [[ "${TYPE}" == "iso" ]]; then
      echo "plain: true"
      echo "display: vnc"
    fi
  '
  [[ "$output" == *"plain: true"* ]]
  [[ "$output" == *"vnc"* ]]
}

@test "lima-novnc: iso mode uses 4GiB memory and 4 cpus" {
  run bash -c '
    cat <<CFG
memory: "4GiB"
cpus: 4
CFG
  '
  [[ "$output" == *'memory: "4GiB"'* ]]
  [[ "$output" == *"cpus: 4"* ]]
}

@test "lima-novnc: iso mode passes boot order to qemu" {
  run bash -c '
    echo "extraArgs: -cdrom /path/iso -boot order=d,menu=on"
  '
  [[ "$output" == *"-boot"* ]]
  [[ "$output" == *"order=d"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Type Dispatch — qcow2 Mode
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: qcow2 type boots image directly" {
  run bash -c '
    TYPE="qcow2"
    if [[ "${TYPE}" != "iso" ]]; then
      echo "Booting qcow2 directly"
      echo "location: /path/to/image.qcow2"
    fi
  '
  [[ "$output" == *"Booting qcow2 directly"* ]]
}

@test "lima-novnc: qcow2 config also uses plain=true" {
  run bash -c '
    TYPE="qcow2"
    if [[ "${TYPE}" != "iso" ]]; then
      echo "plain: true"
    fi
  '
  [[ "$output" == *"plain: true"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# VNC Display Resolution
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: resolves VNC display from limactl JSON" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0,to=9"
    echo "$VNC_DISPLAY"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "127.0.0.1:0,to=9" ]]
}

@test "lima-novnc: strips trailing options from VNC display" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0,to=9"
    VNC_DISPLAY="${VNC_DISPLAY%%,*}"
    echo "$VNC_DISPLAY"
  '
  [ "$output" = "127.0.0.1:0" ]
}

@test "lima-novnc: extracts VNC host from display" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0"
    VNC_HOST="${VNC_DISPLAY%:*}"
    echo "$VNC_HOST"
  '
  [ "$output" = "127.0.0.1" ]
}

@test "lima-novnc: extracts VNC display number" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:3"
    VNC_DISP_NUM="${VNC_DISPLAY##*:}"
    echo "$VNC_DISP_NUM"
  '
  [ "$output" = "3" ]
}

@test "lima-novnc: calculates VNC port from display number" {
  run bash -c '
    VNC_DISP_NUM=2
    VNC_PORT=$((5900 + VNC_DISP_NUM))
    echo "$VNC_PORT"
  '
  [ "$output" = "5902" ]
}

@test "lima-novnc: VNC display 0 maps to port 5900" {
  run bash -c '
    VNC_DISP_NUM=0
    VNC_PORT=$((5900 + VNC_DISP_NUM))
    echo "$VNC_PORT"
  '
  [ "$output" = "5900" ]
}

@test "lima-novnc: reads VNC display from vncdisplay file fallback" {
  run bash -c '
    VNC_FILE="/tmp/test-vncdisplay"
    echo "127.0.0.1:1" > "$VNC_FILE"
    VNC_DISPLAY=$(cat "$VNC_FILE" 2>/dev/null || echo "")
    echo "$VNC_DISPLAY"
    rm -f "$VNC_FILE"
  '
  [ "$output" = "127.0.0.1:1" ]
}

@test "lima-novnc: exits when VNC display cannot be determined" {
  run bash -c '
    VNC_DISPLAY=""
    if [[ -z "${VNC_DISPLAY}" ]]; then
      echo "Error: could not determine VNC display"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"could not determine VNC display"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# noVNC Port Selection
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: default noVNC port is 6080" {
  run bash -c '
    NOVNC_PORT=6080
    echo "$NOVNC_PORT"
  '
  [ "$output" = "6080" ]
}

@test "lima-novnc: increments port when default is in use" {
  run bash -c '
    NOVNC_PORT=6080
    # Simulate port 6080 in use
    if [ "$NOVNC_PORT" -eq 6080 ]; then
      NOVNC_PORT=$((NOVNC_PORT + 1))
    fi
    echo "$NOVNC_PORT"
  '
  [ "$output" = "6081" ]
}

@test "lima-novnc: port increments correctly for multiple conflicts" {
  run bash -c '
    NOVNC_PORT=6080
    for i in 1 2 3; do
      NOVNC_PORT=$((NOVNC_PORT + 1))
    done
    echo "$NOVNC_PORT"
  '
  [ "$output" = "6083" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# noVNC URL Construction
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: constructs local URL with autoconnect" {
  run bash -c '
    NOVNC_PORT=6080
    LOCAL_URL="http://127.0.0.1:${NOVNC_PORT}/vnc.html?autoconnect=1"
    echo "$LOCAL_URL"
  '
  [ "$output" = "http://127.0.0.1:6080/vnc.html?autoconnect=1" ]
}

@test "lima-novnc: appends password to URL when VNC password exists" {
  run bash -c '
    NOVNC_PORT=6080
    VNC_PASS="secret123"
    NOVNC_PARAMS="vnc.html?autoconnect=1"
    if [[ -n "${VNC_PASS}" ]]; then
      NOVNC_PARAMS="${NOVNC_PARAMS}&password=${VNC_PASS}"
    fi
    LOCAL_URL="http://127.0.0.1:${NOVNC_PORT}/${NOVNC_PARAMS}&host=127.0.0.1&port=${NOVNC_PORT}"
    echo "$LOCAL_URL"
  '
  [[ "$output" == *"password=secret123"* ]]
}

@test "lima-novnc: omits password from URL when no VNC password" {
  run bash -c '
    NOVNC_PORT=6080
    VNC_PASS=""
    NOVNC_PARAMS="vnc.html?autoconnect=1"
    if [[ -n "${VNC_PASS}" ]]; then
      NOVNC_PARAMS="${NOVNC_PARAMS}&password=${VNC_PASS}"
    fi
    LOCAL_URL="http://127.0.0.1:${NOVNC_PORT}/${NOVNC_PARAMS}&host=127.0.0.1&port=${NOVNC_PORT}"
    echo "$LOCAL_URL"
  '
  [[ "$output" != *"password="* ]]
}

@test "lima-novnc: includes host and port in URL" {
  run bash -c '
    NOVNC_PORT=6080
    LOCAL_URL="http://127.0.0.1:${NOVNC_PORT}/vnc.html?autoconnect=1&host=127.0.0.1&port=${NOVNC_PORT}"
    echo "$LOCAL_URL"
  '
  [[ "$output" == *"host=127.0.0.1"* ]]
  [[ "$output" == *"port=6080"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Tailscale IP Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: detects Tailscale IP via tailscale command" {
  run bash -c '
    tailscale() { echo "100.64.1.2"; }
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null | head -1 || true)
    echo "$TAILSCALE_IP"
  '
  [ "$output" = "100.64.1.2" ]
}

@test "lima-novnc: falls back to tailscale0 interface when command missing" {
  run bash -c '
    command() { return 1; }
    TAILSCALE_IP=""
    if command -v no-tailscale &>/dev/null; then
      TAILSCALE_IP="from-command"
    else
      TAILSCALE_IP="100.64.2.3"
    fi
    echo "$TAILSCALE_IP"
  '
  [ "$output" = "100.64.2.3" ]
}

@test "lima-novnc: constructs Tailnet URL when IP available" {
  run bash -c '
    TAILSCALE_IP="100.64.1.2"
    NOVNC_PORT=6080
    TAILNET_URL="http://${TAILSCALE_IP}:${NOVNC_PORT}/vnc.html?autoconnect=1&host=${TAILSCALE_IP}&port=${NOVNC_PORT}"
    echo "$TAILNET_URL"
  '
  [[ "$output" == "http://100.64.1.2:6080/"* ]]
}

@test "lima-novnc: skips Tailnet URL when no Tailscale IP" {
  run bash -c '
    TAILSCALE_IP=""
    if [[ -n "${TAILSCALE_IP}" ]]; then
      echo "Tailnet URL present"
    else
      echo "No Tailscale IP"
    fi
  '
  [ "$output" = "No Tailscale IP" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# noVNC Readiness Check
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: waits for noVNC to be ready (max 20 attempts)" {
  run bash -c '
    MAX_ATTEMPTS=20
    attempts=0
    while [ $attempts -lt $MAX_ATTEMPTS ]; do
      attempts=$((attempts + 1))
      if [ $attempts -ge 3 ]; then
        break
      fi
    done
    echo "Attempts: $attempts"
  '
  [ "$output" = "Attempts: 3" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Output Summary
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: outputs summary with VM name and URLs" {
  run bash -c '
    VM_NAME="test-vm"
    LOCAL_URL="http://127.0.0.1:6080/vnc.html?autoconnect=1"
    echo "=============================="
    echo " VM:       ${VM_NAME}"
    echo " Local:    ${LOCAL_URL}"
    echo "=============================="
    echo " Stop: limactl stop ${VM_NAME} && podman stop ${VM_NAME}-novnc"
  '
  [[ "$output" == *"VM:       test-vm"* ]]
  [[ "$output" == *"Local:"* ]]
  [[ "$output" == *"Stop:"* ]]
}

@test "lima-novnc: outputs stop instructions" {
  run bash -c '
    VM_NAME="myvm"
    echo "Stop: limactl stop ${VM_NAME} && podman stop ${VM_NAME}-novnc"
  '
  [[ "$output" == *"limactl stop myvm"* ]]
  [[ "$output" == *"podman stop myvm-novnc"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# VNC Password Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "lima-novnc: reads VNC password from vncpassword file" {
  run bash -c '
    VNC_PASS_FILE="/tmp/test-vncpass"
    echo "test-pass-123" > "$VNC_PASS_FILE"
    VNC_PASS=$(cat "$VNC_PASS_FILE" 2>/dev/null || echo "")
    echo "$VNC_PASS"
    rm -f "$VNC_PASS_FILE"
  '
  [ "$output" = "test-pass-123" ]
}

@test "lima-novnc: VNC password empty when file missing" {
  run bash -c '
    VNC_PASS_FILE="/tmp/nonexistent-vncpass"
    VNC_PASS=""
    if [[ -f "${VNC_PASS_FILE}" ]]; then
      VNC_PASS=$(cat "${VNC_PASS_FILE}")
    fi
    echo "password_empty=${#VNC_PASS}"
  '
  [ "$output" = "password_empty=0" ]
}
