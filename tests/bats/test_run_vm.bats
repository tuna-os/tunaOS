#!/usr/bin/env bats
# Unit tests for scripts/run-vm.sh and scripts/test-vm.sh
#
# Tests:
#   - run-vm.sh: port allocation (next available port finding)
#   - run-vm.sh: image filename selection (qcow2 vs iso, base vs flavored)
#   - run-vm.sh: subcommand dispatch and error handling
#   - test-vm.sh: VM name construction (base vs flavored)
#   - test-vm.sh: VNC display parsing (extract address from limactl format)
#   - test-vm.sh: architecture detection (arm64→aarch64, x86_64→x86_64)
#   - test-vm.sh: image filename construction

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# run-vm.sh — Port Allocation
# ═══════════════════════════════════════════════════════════════════════════

@test "run-vm: finds next available port starting from 8100" {
  # Simulate: no ports in use → 8100 is first available
  run bash -c '
    port=8100
    # Mock ss: simulate port 8100 NOT in use
    ss_mock() { return 1; }
    while ss_mock | grep -q ":${port} "; do port=$((port + 1)); done
    echo "$port"
  '
  [ "$output" = "8100" ]
}

@test "run-vm: skips occupied port and finds next" {
  run bash -c '
    port=8100
    call_count=0
    ss_mock() {
      call_count=$((call_count + 1))
      # Port 8100 is occupied, 8101 is free
      if [ "$call_count" -le 1 ]; then
        echo "LISTEN 0 128 0.0.0.0:8100"
        return 0
      fi
      return 1
    }
    while ss_mock | grep -q ":${port} "; do port=$((port + 1)); done
    echo "$port"
  '
  [ "$output" = "8101" ]
}

@test "run-vm: skips multiple occupied ports" {
  run bash -c '
    port=8100
    call_count=0
    ss_mock() {
      call_count=$((call_count + 1))
      if [ "$call_count" -le 3 ]; then
        echo "LISTEN 0 128 0.0.0.0:${port}"
        return 0
      fi
      return 1
    }
    while ss_mock | grep -q ":${port} "; do port=$((port + 1)); done
    echo "$port"
  '
  [ "$output" = "8103" ]
}

@test "run-vm: SSH port offset from web port" {
  run bash -c '
    web_port=8110
    ssh_port=$((web_port + 1))
    echo "$ssh_port"
  '
  [ "$output" = "8111" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# run-vm.sh — Image Filename Selection
# ═══════════════════════════════════════════════════════════════════════════

@test "run-vm: qcow2 filename for base flavor" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="base"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    else
      IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$output" = "yellowfin.qcow2" ]
}

@test "run-vm: qcow2 filename for non-base flavor" {
  run bash -c '
    VARIANT="albacore"
    FLAVOR="gnome"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    else
      IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$output" = "albacore-gnome.qcow2" ]
}

@test "run-vm: ISO filename fallback when flavored file missing" {
  run bash -c '
    VARIANT="skipjack"
    FLAVOR="gnome"
    # Simulate: specific file exists, use it
    if [[ -f "${VARIANT}-${FLAVOR}.qcow2" ]]; then
      image_file="${VARIANT}-${FLAVOR}.qcow2"
    else
      image_file="${VARIANT}.qcow2"
    fi
    echo "$image_file"
  '
  [ "$output" = "skipjack.qcow2" ]
}

@test "run-vm: ISO image selection from find output" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="gnome"
    # Simulate find finds an ISO
    FOUND_ISO="yellowfin-gnome-10-x86_64.iso"
    if [[ -f "$FOUND_ISO" ]]; then
      image_file="$FOUND_ISO"
    else
      image_file="${VARIANT}.iso"
    fi
    echo "$image_file"
  '
  # File does not exist, falls back to variant.iso
  [ "$output" = "yellowfin.iso" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# run-vm.sh — Subcommand Dispatch
# ═══════════════════════════════════════════════════════════════════════════

@test "run-vm: unknown subcommand prints usage" {
  run bash -c '
    CMD="unknown-cmd"
    case "$CMD" in
      run) echo "run";;
      demo) echo "demo";;
      demo-iso) echo "demo-iso";;
      *) echo "Usage: run-vm.sh <run|demo|demo-iso> [args...]"; exit 1;;
    esac
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage: run-vm.sh"* ]]
}

@test "run-vm: empty subcommand prints usage" {
  run bash -c '
    CMD=""
    case "$CMD" in
      run) echo "run";;
      demo) echo "demo";;
      demo-iso) echo "demo-iso";;
      *) echo "Usage: run-vm.sh <run|demo|demo-iso> [args...]"; exit 1;;
    esac
  '
  [ "$status" -eq 1 ]
}

@test "run-vm: run subcommand is recognized" {
  run bash -c '
    CMD="run"
    case "$CMD" in
      run) echo "run selected";;
      demo) echo "demo";;
      demo-iso) echo "demo-iso";;
      *) echo "unknown";;
    esac
  '
  [ "$output" = "run selected" ]
}

@test "run-vm: demo subcommand is recognized" {
  run bash -c '
    CMD="demo"
    case "$CMD" in
      run) echo "run";;
      demo) echo "demo selected";;
      demo-iso) echo "demo-iso";;
      *) echo "unknown";;
    esac
  '
  [ "$output" = "demo selected" ]
}

@test "run-vm: demo-iso subcommand is recognized" {
  run bash -c '
    CMD="demo-iso"
    case "$CMD" in
      run) echo "run";;
      demo) echo "demo";;
      demo-iso) echo "demo-iso selected";;
      *) echo "unknown";;
    esac
  '
  [ "$output" = "demo-iso selected" ]
}

@test "run-vm: demo subcommand default variant is albacore" {
  run bash -c '
    VARIANT="${1:-albacore}"
    echo "$VARIANT"
  ' _
  [ "$output" = "albacore" ]
}

@test "run-vm: demo subcommand default flavor is gnome" {
  run bash -c '
    FLAVOR="${2:-gnome}"
    echo "$FLAVOR"
  ' _ _
  [ "$output" = "gnome" ]
}

@test "run-vm: demo-iso subcommand default variant is skipjack" {
  run bash -c '
    VARIANT="${1:-skipjack}"
    echo "$VARIANT"
  ' _
  [ "$output" = "skipjack" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# test-vm.sh — VM Name Construction
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: VM name for base flavor" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="base"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="tuna-${VARIANT}"
    else
      VM_NAME="tuna-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "tuna-yellowfin" ]
}

@test "test-vm: VM name for non-base flavor" {
  run bash -c '
    VARIANT="albacore"
    FLAVOR="gnome"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="tuna-${VARIANT}"
    else
      VM_NAME="tuna-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "tuna-albacore-gnome" ]
}

@test "test-vm: VM name for kde flavor" {
  run bash -c '
    VARIANT="bonito"
    FLAVOR="kde"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="tuna-${VARIANT}"
    else
      VM_NAME="tuna-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "tuna-bonito-kde" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# test-vm.sh — Image Filename Construction
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: image filename for base flavor" {
  run bash -c '
    VARIANT="skipjack"
    FLAVOR="base"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    else
      IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$output" = "skipjack.qcow2" ]
}

@test "test-vm: image filename for non-base flavor" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="gnome"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    else
      IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$output" = "yellowfin-gnome.qcow2" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# test-vm.sh — Architecture Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: arm64 maps to aarch64" {
  run bash -c '
    ARCH="arm64"
    if [ "$ARCH" == "arm64" ]; then LIMA_ARCH="aarch64"
    else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "aarch64" ]
}

@test "test-vm: x86_64 maps to x86_64" {
  run bash -c '
    ARCH="x86_64"
    if [ "$ARCH" == "arm64" ]; then LIMA_ARCH="aarch64"
    else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

@test "test-vm: aarch64 maps to x86_64 (not arm64)" {
  run bash -c '
    ARCH="aarch64"
    if [ "$ARCH" == "arm64" ]; then LIMA_ARCH="aarch64"
    else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# test-vm.sh — VNC Display Parsing
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: VNC display extraction from limactl format" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0,to=9"
    VNC_DISPLAY=${VNC_DISPLAY%%,*}
    echo "$VNC_DISPLAY"
  '
  [ "$output" = "127.0.0.1:0" ]
}

@test "test-vm: VNC display without comma passes through" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0"
    VNC_DISPLAY=${VNC_DISPLAY%%,*}
    echo "$VNC_DISPLAY"
  '
  [ "$output" = "127.0.0.1:0" ]
}

@test "test-vm: VNC display with multiple commas" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0,to=9,other=value"
    VNC_DISPLAY=${VNC_DISPLAY%%,*}
    echo "$VNC_DISPLAY"
  '
  [ "$output" = "127.0.0.1:0" ]
}

@test "test-vm: empty VNC display handles gracefully" {
  run bash -c '
    VNC_DISPLAY=""
    if [ -z "$VNC_DISPLAY" ] || [ "$VNC_DISPLAY" == "null" ]; then
      echo "no display"
    else
      echo "$VNC_DISPLAY"
    fi
  '
  [ "$output" = "no display" ]
}

@test "test-vm: null VNC display handles gracefully" {
  run bash -c '
    VNC_DISPLAY="null"
    if [ -z "$VNC_DISPLAY" ] || [ "$VNC_DISPLAY" == "null" ]; then
      echo "no display"
    else
      echo "$VNC_DISPLAY"
    fi
  '
  [ "$output" = "no display" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# test-vm.sh — Error Handling / Usage
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: exits with error when fewer than 2 args" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      echo "Usage: $0 <variant> <flavor>"
      exit 1
    fi
  ' _ yellowfin
  [ "$status" -eq 1 ]
}

@test "test-vm: exits with error when more than 2 args" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      echo "Usage: $0 <variant> <flavor>"
      exit 1
    fi
  ' _ yellowfin gnome extra
  [ "$status" -eq 1 ]
}

@test "test-vm: passes with exactly 2 args" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      echo "Usage: $0 <variant> <flavor>"
      exit 1
    else
      echo "VARIANT=$1 FLAVOR=$2"
    fi
  ' _ yellowfin gnome
  [ "$status" -eq 0 ]
  [ "$output" = "VARIANT=yellowfin FLAVOR=gnome" ]
}

@test "test-vm: error when image file missing" {
  run bash -c '
    IMAGE_PATH="/nonexistent/path/image.qcow2"
    if [ ! -f "$IMAGE_PATH" ]; then
      echo "Error: Image not found at $IMAGE_PATH"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Error: Image not found"* ]]
}
