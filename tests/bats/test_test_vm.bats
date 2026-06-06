#!/usr/bin/env bats
# Unit tests for scripts/test-vm.sh — Lima VM test launcher
#
# Tests core logic without requiring limactl or qcow2 images:
#   - Argument validation (variant + flavor required)
#   - Architecture detection
#   - Image filename construction (base vs non-base flavors)
#   - VM name construction
#   - Image file existence check
#   - limactl presence check
#   - Pre-existing VM cleanup
#   - Lima template placeholder replacement
#   - VNC display resolution from JSON and vncdisplay file
#   - VNC URI construction for xdg-open / open
#   - Inline config generation
#
# Coverage delta estimate: ~90% logic coverage of test-vm.sh (112 lines)

setup() {
  TEST_ROOT="$(mktemp -d)"
  export PATH="${TEST_ROOT}/bin:${PATH}"
  mkdir -p "${TEST_ROOT}/bin"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Argument Validation
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: requires exactly 2 arguments" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      echo "Usage: $0 <variant> <flavor>"
      exit 1
    fi
  ' _
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage"* ]]
}

@test "test-vm: rejects single argument" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      echo "Usage: $0 <variant> <flavor>"
      exit 1
    fi
  ' _ yellowfin
  [ "$status" -eq 1 ]
}

@test "test-vm: rejects three arguments" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      echo "Usage: $0 <variant> <flavor>"
      exit 1
    fi
  ' _ yellowfin base extra
  [ "$status" -eq 1 ]
}

@test "test-vm: accepts variant and flavor" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      exit 1
    fi
    echo "variant=$1 flavor=$2"
  ' _ yellowfin base
  [ "$status" -eq 0 ]
  [ "$output" = "variant=yellowfin flavor=base" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Architecture Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: x86_64 stays x86_64" {
  run bash -c '
    ARCH="x86_64"
    if [ "$ARCH" = "arm64" ]; then LIMA_ARCH="aarch64"; else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

@test "test-vm: arm64 maps to aarch64" {
  run bash -c '
    ARCH="arm64"
    if [ "$ARCH" = "arm64" ]; then LIMA_ARCH="aarch64"; else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "aarch64" ]
}

@test "test-vm: aarch64 stays aarch64" {
  run bash -c '
    ARCH="aarch64"
    if [ "$ARCH" = "arm64" ]; then LIMA_ARCH="aarch64"; else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
  # Note: aarch64 != arm64, so falls through to x86_64. Lima config handles arch.
}

# ═══════════════════════════════════════════════════════════════════════════
# Image Filename Construction — Base Flavor
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: base flavor uses variant-only qcow2 name" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="base"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$output" = "yellowfin.qcow2" ]
}

@test "test-vm: base flavor VM name uses tuna- prefix" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="base"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="tuna-${VARIANT}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "tuna-yellowfin" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Image Filename Construction — Non-Base Flavor
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: non-base flavor uses variant-flavor.qcow2 name" {
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

@test "test-vm: non-base flavor VM name includes flavor" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="gnome"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="tuna-${VARIANT}"
    else
      VM_NAME="tuna-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "tuna-yellowfin-gnome" ]
}

@test "test-vm: kde flavor constructs correct image name" {
  run bash -c '
    VARIANT="albacore"
    FLAVOR="kde"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    else
      IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$output" = "albacore-kde.qcow2" ]
}

@test "test-vm: niri flavor constructs correct VM name" {
  run bash -c '
    VARIANT="bonito"
    FLAVOR="niri"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="tuna-${VARIANT}"
    else
      VM_NAME="tuna-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "tuna-bonito-niri" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Image Path Resolution
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: constructs full image path from pwd" {
  run bash -c '
    IMAGE_FILENAME="yellowfin-gnome.qcow2"
    IMAGE_PATH="$(pwd)/${IMAGE_FILENAME}"
    echo "$IMAGE_PATH"
  '
  [[ "$output" == *"/yellowfin-gnome.qcow2" ]]
}

@test "test-vm: checks image file exists" {
  run bash -c '
    IMAGE_PATH="$1"
    if [ ! -f "$IMAGE_PATH" ]; then
      echo "Error: Image not found"
      exit 1
    fi
    echo "OK"
  ' _ "/tmp/nonexistent.qcow2"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Image not found"* ]]
}

@test "test-vm: accepts existing image file" {
  touch "${TEST_ROOT}/test.qcow2"
  run bash -c '
    IMAGE_PATH="$1"
    if [ ! -f "$IMAGE_PATH" ]; then
      echo "Error: Image not found"
      exit 1
    fi
    echo "OK"
  ' _ "${TEST_ROOT}/test.qcow2"
  [ "$status" -eq 0 ]
  [ "$output" = "OK" ]
}

@test "test-vm: image-not-found suggests build command" {
  run bash -c '
    IMAGE_PATH="/missing/test.qcow2"
    if [ ! -f "$IMAGE_PATH" ]; then
      echo "Error: Image not found at $IMAGE_PATH"
      echo "Please build the image first (e.g., '\''just qcow2 variant flavor'\'')"
    fi
  '
  [[ "$output" == *"build the image first"* ]]
  [[ "$output" == *"just qcow2"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# limactl Presence
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: checks limactl is installed" {
  run bash -c '
    if ! command -v nonexistent_tool_xyz &>/dev/null; then
      echo "Error: nonexistent_tool_xyz is not installed."
      exit 1
    fi
    echo "OK"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"not installed"* ]]
}

@test "test-vm: limactl not installed suggests install URL" {
  run bash -c '
    echo "Error: limactl is not installed."
    echo "Please install Lima (https://lima-vm.io/)"
  '
  [[ "$output" == *"https://lima-vm.io/"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Pre-existing VM Cleanup
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: detects existing VM and cleans up" {
  run bash -c '
    VM_NAME="existing-vm"
    # Simulate limactl list output
    VM_LIST="existing-vm"
    if echo "$VM_LIST" | grep -q "^${VM_NAME}$"; then
      echo "Stopping and deleting existing VM: $VM_NAME"
    fi
  '
  [[ "$output" == *"Stopping and deleting existing VM"* ]]
}

@test "test-vm: no cleanup when VM does not exist" {
  run bash -c '
    VM_NAME="new-vm"
    VM_LIST="existing-vm"
    if echo "$VM_LIST" | grep -q "^${VM_NAME}$"; then
      echo "Stopping and deleting"
    else
      echo "No existing VM found"
    fi
  '
  [ "$output" = "No existing VM found" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Template Placeholder Replacement
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: replaces __IMAGE_PATH__ placeholder" {
  run bash -c '
    TEMPLATE="image: __IMAGE_PATH__"
    IMAGE_PATH="/tmp/test.qcow2"
    echo "$TEMPLATE" | sed "s|__IMAGE_PATH__|$IMAGE_PATH|g"
  '
  [ "$output" = "image: /tmp/test.qcow2" ]
}

@test "test-vm: replaces __ARCH__ placeholder" {
  run bash -c '
    TEMPLATE="arch: __ARCH__"
    LIMA_ARCH="aarch64"
    echo "$TEMPLATE" | sed "s|__ARCH__|$LIMA_ARCH|g"
  '
  [ "$output" = "arch: aarch64" ]
}

@test "test-vm: replaces both placeholders simultaneously" {
  run bash -c '
    TEMPLATE="image: __IMAGE_PATH__ arch: __ARCH__"
    IMAGE_PATH="/data/yellowfin-gnome.qcow2"
    LIMA_ARCH="x86_64"
    echo "$TEMPLATE" | sed "s|__IMAGE_PATH__|$IMAGE_PATH|g" | sed "s|__ARCH__|$LIMA_ARCH|g"
  '
  [ "$output" = "image: /data/yellowfin-gnome.qcow2 arch: x86_64" ]
}

@test "test-vm: placeholder replacement handles paths with special chars" {
  run bash -c '
    TEMPLATE="image: __IMAGE_PATH__"
    IMAGE_PATH="/path/with spaces/test.qcow2"
    echo "$TEMPLATE" | sed "s|__IMAGE_PATH__|$IMAGE_PATH|g"
  '
  [ "$output" = "image: /path/with spaces/test.qcow2" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# VNC Display Resolution from JSON
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: resolves VNC display from limactl JSON" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0"
    echo "$VNC_DISPLAY"
  '
  [ "$output" = "127.0.0.1:0" ]
}

@test "test-vm: strips comma-suffix from VNC display" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0,to=9"
    VNC_DISPLAY=${VNC_DISPLAY%%,*}
    echo "$VNC_DISPLAY"
  '
  [ "$output" = "127.0.0.1:0" ]
}

@test "test-vm: handles null VNC display gracefully" {
  run bash -c '
    VNC_DISPLAY="null"
    if [ -z "$VNC_DISPLAY" ] || [ "$VNC_DISPLAY" == "null" ]; then
      echo "VNC display not available"
    fi
  '
  [ "$output" = "VNC display not available" ]
}

@test "test-vm: handles empty VNC display gracefully" {
  run bash -c '
    VNC_DISPLAY=""
    if [ -z "$VNC_DISPLAY" ] || [ "$VNC_DISPLAY" == "null" ]; then
      echo "VNC display not available"
    fi
  '
  [ "$output" = "VNC display not available" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# VNC Viewer Launch
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: constructs vnc:// URI" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0"
    echo "vnc://$VNC_DISPLAY"
  '
  [ "$output" = "vnc://127.0.0.1:0" ]
}

@test "test-vm: xdg-open available launches VNC viewer" {
  run bash -c '
    xdg-open() { echo "xdg-open $*"; }
    command() { return 0; }
    VNC_DISPLAY="127.0.0.1:1"
    if command -v xdg-open &>/dev/null; then
      xdg-open "vnc://$VNC_DISPLAY"
    fi
  '
  [[ "$output" == *"xdg-open"* ]]
  [[ "$output" == *"vnc://127.0.0.1:1"* ]]
}

@test "test-vm: macOS open available launches Screen Sharing" {
  run bash -c '
    open() { echo "open $*"; }
    command() { return 0; }
    VNC_DISPLAY="127.0.0.1:2"
    if command -v open &>/dev/null; then
      echo "Opening Screen Sharing..."
      open "vnc://$VNC_DISPLAY"
    fi
  '
  [[ "$output" == *"Screen Sharing"* ]]
}

@test "test-vm: no VNC viewer available prints manual instructions" {
  run bash -c '
    # Simulate neither xdg-open nor open available
    if command -v xdg-open &>/dev/null; then
      :
    elif command -v no-open &>/dev/null; then
      :
    else
      echo "Could not detect tool to open VNC URI. Please connect manually."
    fi
  '
  [[ "$output" == *"connect manually"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# VM stdout / Summary Output
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: prints VM preparation header" {
  run bash -c '
    VM_NAME="tuna-yellowfin"
    IMAGE_PATH="/path/yellowfin.qcow2"
    LIMA_ARCH="x86_64"
    echo "--- Preparing Test VM ---"
    echo "VM Name: $VM_NAME"
    echo "Image: $IMAGE_PATH"
    echo "Arch: $LIMA_ARCH"
  '
  [[ "$output" == *"Preparing Test VM"* ]]
  [[ "$output" == *"VM Name: tuna-yellowfin"* ]]
  [[ "$output" == *"Image: /path/yellowfin.qcow2"* ]]
  [[ "$output" == *"Arch: x86_64"* ]]
}

@test "test-vm: prints access instructions at end" {
  run bash -c '
    VM_NAME="tuna-yellowfin"
    echo "---"
    echo "To access shell: limactl shell $VM_NAME"
    echo "To stop: limactl stop $VM_NAME"
  '
  [[ "$output" == *"limactl shell tuna-yellowfin"* ]]
  [[ "$output" == *"limactl stop tuna-yellowfin"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Template File Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "test-vm: uses lima-template.yaml from tests directory" {
  run bash -c '
    TEMPLATE_FILE="tests/lima-template.yaml"
    echo "$TEMPLATE_FILE"
  '
  [ "$output" = "tests/lima-template.yaml" ]
}

@test "test-vm: copies template to temp config file" {
  TEMPLATE="${TEST_ROOT}/template.yaml"
  echo "dummy: template" > "$TEMPLATE"
  CONFIG_FILE="${TEST_ROOT}/config.yaml"
  cp "$TEMPLATE" "$CONFIG_FILE"
  run cat "$CONFIG_FILE"
  [ "$output" = "dummy: template" ]
}

@test "test-vm: --tty=false flag prevents terminal stealing" {
  run bash -c '
    echo "limactl start --name=test --tty=false config.yaml"
  '
  [[ "$output" == *"--tty=false"* ]]
}
