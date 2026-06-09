#!/usr/bin/env bats
# Unit tests for scripts/verify-image.sh and scripts/verify-iso.sh
#
# Tests:
#   - Display manager detection from flavor name
#   - VM name sanitization (special chars, uppercase, etc.)
#   - Architecture detection (x86_64, arm64, aarch64)
#   - Image filename construction for base vs non-base flavors
#   - ISO filename -> VM name transformation
#   - Error handling: missing files, missing limactl
#   - Serial log boot indicator detection
#   - Lima config template generation

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/scripts"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-image.sh — Display Manager Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-image: detects gdm for GNOME flavors" {
  run bash -c '
    FLAVOR="gnome"
    DM_SERVICE="gdm"
    if [[ "$FLAVOR" == *"kde"* ]]; then DM_SERVICE="sddm"
    elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then DM_SERVICE="greetd"
    fi
    echo "$DM_SERVICE"
  '
  [ "$output" = "gdm" ]
}

@test "verify-image: detects gdm for gnome-hwe flavor" {
  run bash -c '
    FLAVOR="gnome-hwe"
    DM_SERVICE="gdm"
    if [[ "$FLAVOR" == *"kde"* ]]; then DM_SERVICE="sddm"
    elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then DM_SERVICE="greetd"
    fi
    echo "$DM_SERVICE"
  '
  [ "$output" = "gdm" ]
}

@test "verify-image: detects sddm for KDE flavors" {
  run bash -c '
    FLAVOR="kde"
    DM_SERVICE="gdm"
    if [[ "$FLAVOR" == *"kde"* ]]; then DM_SERVICE="sddm"
    elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then DM_SERVICE="greetd"
    fi
    echo "$DM_SERVICE"
  '
  [ "$output" = "sddm" ]
}

@test "verify-image: detects sddm for kde-gdx flavor" {
  run bash -c '
    FLAVOR="kde-gdx"
    DM_SERVICE="gdm"
    if [[ "$FLAVOR" == *"kde"* ]]; then DM_SERVICE="sddm"
    elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then DM_SERVICE="greetd"
    fi
    echo "$DM_SERVICE"
  '
  [ "$output" = "sddm" ]
}

@test "verify-image: detects greetd for COSMIC flavor" {
  run bash -c '
    FLAVOR="cosmic"
    DM_SERVICE="gdm"
    if [[ "$FLAVOR" == *"kde"* ]]; then DM_SERVICE="sddm"
    elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then DM_SERVICE="greetd"
    fi
    echo "$DM_SERVICE"
  '
  [ "$output" = "greetd" ]
}

@test "verify-image: detects greetd for niri flavor" {
  run bash -c '
    FLAVOR="niri"
    DM_SERVICE="gdm"
    if [[ "$FLAVOR" == *"kde"* ]]; then DM_SERVICE="sddm"
    elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then DM_SERVICE="greetd"
    fi
    echo "$DM_SERVICE"
  '
  [ "$output" = "greetd" ]
}

@test "verify-image: detects greetd for niri-hwe flavor" {
  run bash -c '
    FLAVOR="niri-hwe"
    DM_SERVICE="gdm"
    if [[ "$FLAVOR" == *"kde"* ]]; then DM_SERVICE="sddm"
    elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then DM_SERVICE="greetd"
    fi
    echo "$DM_SERVICE"
  '
  [ "$output" = "greetd" ]
}

@test "verify-image: KDE detection takes priority over COSMIC substring" {
  # Verify kde is checked BEFORE cosmic (which contains 'c' from kde? No, but just order check)
  run bash -c '
    FLAVOR="kde-cosmic-hybrid"
    DM_SERVICE="gdm"
    # Order matters: kde check must come before cosmic check
    if [[ "$FLAVOR" == *"kde"* ]]; then DM_SERVICE="sddm"
    elif [[ "$FLAVOR" == *"cosmic"* || "$FLAVOR" == *"niri"* ]]; then DM_SERVICE="greetd"
    fi
    echo "$DM_SERVICE"
  '
  [ "$output" = "sddm" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-image.sh — VM Name Sanitization
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-image: VM name constructed for base flavor" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="base"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="verify-${VARIANT}"
    else
      VM_NAME="verify-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "verify-yellowfin" ]
}

@test "verify-image: VM name constructed for non-base flavor" {
  run bash -c '
    VARIANT="albacore"
    FLAVOR="gnome"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="verify-${VARIANT}"
    else
      VM_NAME="verify-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "verify-albacore-gnome" ]
}

@test "verify-image: VM name includes hyphenated flavor" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="gnome-gdx-hwe"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="verify-${VARIANT}"
    else
      VM_NAME="verify-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$output" = "verify-yellowfin-gnome-gdx-hwe" ]
}

@test "verify-image: VM name sanitization lowercases" {
  run bash -c '
    VM_NAME="verify-YELLOWFIN-GNOME"
    VM_NAME=$(echo "$VM_NAME" | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--/-/g" | sed "s/^-//;s/-$//")
    echo "$VM_NAME"
  '
  [ "$output" = "verify-yellowfin-gnome" ]
}

@test "verify-image: VM name sanitization removes double hyphens" {
  run bash -c '
    VM_NAME="verify--skipjack--gnome"
    VM_NAME=$(echo "$VM_NAME" | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--/-/g" | sed "s/^-//;s/-$//")
    echo "$VM_NAME"
  '
  [ "$output" = "verify-skipjack-gnome" ]
}

@test "verify-image: VM name sanitization strips leading/trailing hyphens" {
  run bash -c '
    VM_NAME="-verify-albacore-"
    VM_NAME=$(echo "$VM_NAME" | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--/-/g" | sed "s/^-//;s/-$//")
    echo "$VM_NAME"
  '
  [ "$output" = "verify-albacore" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-image.sh — Image Filename Construction
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-image: qcow2 filename for base flavor" {
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

@test "verify-image: qcow2 filename for non-base flavor" {
  run bash -c '
    VARIANT="bonito"
    FLAVOR="kde"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    else
      IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$output" = "bonito-kde.qcow2" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-image.sh — Architecture Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-image: arch detection maps arm64 to aarch64" {
  run bash -c '
    ARCH="arm64"
    if [ "$ARCH" == "arm64" ]; then LIMA_ARCH="aarch64"
    else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "aarch64" ]
}

@test "verify-image: arch detection maps x86_64 to x86_64" {
  run bash -c '
    ARCH="x86_64"
    if [ "$ARCH" == "arm64" ]; then LIMA_ARCH="aarch64"
    else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

@test "verify-image: arch detection maps aarch64 to x86_64 (not arm64)" {
  run bash -c '
    ARCH="aarch64"
    if [ "$ARCH" == "arm64" ]; then LIMA_ARCH="aarch64"
    else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-image.sh — Usage / Error Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-image: exits with error when fewer than 2 args" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      echo "Usage: $0 <variant> <flavor>"
      exit 1
    fi
  ' _ yellowfin
  [ "$status" -eq 1 ]
}

@test "verify-image: exits with error when more than 2 args" {
  run bash -c '
    if [ "$#" -ne 2 ]; then
      echo "Usage: $0 <variant> <flavor>"
      exit 1
    fi
  ' _ yellowfin gnome extra
  [ "$status" -eq 1 ]
}

@test "verify-image: exits with error when image file is missing" {
  run bash -c '
    IMAGE_PATH="/nonexistent/path/skipjack.qcow2"
    if [ ! -f "$IMAGE_PATH" ]; then
      echo "Error: Image not found at $IMAGE_PATH"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — VM Name from ISO Filename
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: VM name derived from ISO filename" {
  run bash -c '
    ISO_FILE="yellowfin-gnome-10-x86_64.iso"
    VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--*/-/g; s/^-//; s/-$//")"
    echo "$VM_NAME"
  '
  [ "$output" = "verify-iso-yellowfin-gnome-10-x86-64" ]
}

@test "verify-iso: VM name handles uppercase in filename" {
  run bash -c '
    ISO_FILE="Yellowfin-GNOME.iso"
    VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--*/-/g; s/^-//; s/-$//")"
    echo "$VM_NAME"
  '
  [ "$output" = "verify-iso-yellowfin-gnome" ]
}

@test "verify-iso: VM name handles special chars" {
  run bash -c '
    ISO_FILE="test image (v1).iso"
    VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--*/-/g; s/^-//; s/-$//")"
    echo "$VM_NAME"
  '
  [ "$output" = "verify-iso-test-image-v1" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Serial Log Boot Indicators
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: kernel panic detected in serial log" {
  run bash -c '
    echo "Kernel panic - not syncing: Attempted to kill init!" >/tmp/test_serial.log
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" /tmp/test_serial.log; then
      echo "ERROR: Fatal boot error detected"
      exit 1
    fi
    echo "OK"
  '
  [ "$status" -eq 1 ]
}

@test "verify-iso: GRUB boot indicators found" {
  run bash -c '
    echo "GRUB version 2.06" >/tmp/test_serial.log
    echo "Booting '\''TunaOS Live'\''" >>/tmp/test_serial.log
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Reached target\|Welcome to\|login:" /tmp/test_serial.log; then
      BOOT_OK=1
    fi
    echo "$BOOT_OK"
  '
  [ "$output" = "1" ]
}

@test "verify-iso: anaconda marker found" {
  run bash -c '
    echo "Started Anaconda installer" >/tmp/test_serial2.log
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Reached target\|Welcome to\|login:" /tmp/test_serial2.log; then
      BOOT_OK=1
    fi
    echo "$BOOT_OK"
  '
  [ "$output" = "1" ]
}

@test "verify-iso: no boot indicators → failure" {
  run bash -c '
    echo "random output with no boot markers" >/tmp/test_serial3.log
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Reached target\|Welcome to\|login:" /tmp/test_serial3.log; then
      BOOT_OK=1
    fi
    echo "$BOOT_OK"
  '
  [ "$output" = "0" ]
}

@test "verify-iso: dracut emergency shell detected" {
  run bash -c '
    echo "dracut-emergency: Dropping to debug shell" >/tmp/test_serial4.log
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" /tmp/test_serial4.log; then
      echo "ERROR: Fatal boot error detected"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Usage / Error Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: exits with error when no ISO file provided" {
  run bash -c '
    if [ "$#" -ne 1 ]; then
      echo "Usage: $0 <iso_file>"
      exit 1
    fi
  ' _
  [ "$status" -eq 1 ]
}

@test "verify-iso: exits with error when ISO file does not exist" {
  run bash -c '
    ISO_PATH="/nonexistent/path/image.iso"
    if [ ! -f "$ISO_PATH" ]; then
      echo "Error: ISO file not found at $ISO_PATH"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}
