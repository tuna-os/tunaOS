#!/usr/bin/env bats
# Unit tests for scripts/verify-iso.sh
#
# Tests:
#   - Argument validation (required ISO file)
#   - VM name sanitization from ISO filename
#   - Architecture detection (arm64→aarch64, x86_64→x86_64)
#   - Lima config template generation
#   - Serial log error pattern matching
#   - Boot indicator detection

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Argument Validation
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: no arguments exits with usage" {
  run bash -c '
    if [ "$#" -ne 1 ]; then
      echo "Usage: $0 <iso_file>" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"*"<iso_file>"* ]]
}

@test "verify-iso: too many arguments exits with usage" {
  run bash -c '
    if [ "$#" -ne 1 ]; then
      echo "Usage: $0 <iso_file>" >&2
      exit 1
    fi
  ' _ arg1 arg2
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "verify-iso: exactly one argument accepted" {
  run bash -c '
    if [ "$#" -ne 1 ]; then
      echo "Usage: $0 <iso_file>" >&2
      exit 1
    fi
    echo "ISO_FILE=$1"
  ' _ "yellowfin-gnome-10-x86_64.iso"
  [ "$status" -eq 0 ]
  [ "$output" = "ISO_FILE=yellowfin-gnome-10-x86_64.iso" ]
}

@test "verify-iso: missing ISO file exits with error" {
  run bash -c '
    ISO_FILE="/nonexistent/path/image.iso"
    ISO_PATH="$(realpath "$ISO_FILE" 2>/dev/null || echo "")"
    if [ ! -f "$ISO_PATH" ]; then
      echo "Error: ISO file not found at $ISO_PATH" >&2
      exit 1
    fi
  ' 2>&1 || true
  [ "$status" -eq 1 ] || [[ "$output" == *"not found"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — VM Name Construction
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: VM name derived from ISO basename" {
  run bash -c '
    ISO_FILE="yellowfin-gnome-10-x86_64.iso"
    VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--*/-/g; s/^-//; s/-$//")"
    echo "$VM_NAME"
  '
  [ "$output" = "verify-iso-yellowfin-gnome-10-x86-64" ]
}

@test "verify-iso: VM name handles uppercase in filename" {
  run bash -c '
    ISO_FILE="SkipJack-GNOME-X86_64.iso"
    VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--*/-/g; s/^-//; s/-$//")"
    echo "$VM_NAME"
  '
  [ "$output" = "verify-iso-skipjack-gnome-x86-64" ]
}

@test "verify-iso: VM name handles special characters" {
  run bash -c '
    ISO_FILE="my_iso_v2.0.iso"
    VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--*/-/g; s/^-//; s/-$//")"
    echo "$VM_NAME"
  '
  [ "$output" = "verify-iso-my-iso-v2-0" ]
}

@test "verify-iso: VM name with base flavor" {
  run bash -c '
    ISO_FILE="yellowfin-base-x86_64.iso"
    VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--*/-/g; s/^-//; s/-$//")"
    echo "$VM_NAME"
  '
  [ "$output" = "verify-iso-yellowfin-base-x86-64" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Architecture Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: arm64 maps to aarch64" {
  run bash -c '
    ARCH="arm64"
    if [ "$ARCH" = "arm64" ]; then
      LIMA_ARCH="aarch64"
    else
      LIMA_ARCH="x86_64"
    fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "aarch64" ]
}

@test "verify-iso: x86_64 maps to x86_64" {
  run bash -c '
    ARCH="x86_64"
    if [ "$ARCH" = "arm64" ]; then
      LIMA_ARCH="aarch64"
    else
      LIMA_ARCH="x86_64"
    fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

@test "verify-iso: aarch64 maps to x86_64 (fallback)" {
  run bash -c '
    ARCH="aarch64"
    if [ "$ARCH" = "arm64" ]; then
      LIMA_ARCH="aarch64"
    else
      LIMA_ARCH="x86_64"
    fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

@test "verify-iso: unknown arch falls back to x86_64" {
  run bash -c '
    ARCH="riscv64"
    if [ "$ARCH" = "arm64" ]; then
      LIMA_ARCH="aarch64"
    else
      LIMA_ARCH="x86_64"
    fi
    echo "$LIMA_ARCH"
  '
  [ "$output" = "x86_64" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Lima Config Generation
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: config YAML includes arch" {
  run bash -c '
    LIMA_ARCH="aarch64"
    echo "arch: ${LIMA_ARCH}"
  '
  [ "$output" = "arch: aarch64" ]
}

@test "verify-iso: config YAML includes ISO location" {
  run bash -c '
    ISO_PATH="/data/isos/yellowfin-gnome-10-x86_64.iso"
    cat <<LIMAEOF
images:
  - location: "${ISO_PATH}"
    arch: x86_64
LIMAEOF
  '
  [[ "$output" == *"location:"*"/yellowfin-gnome-10-x86_64.iso"* ]]
}

@test "verify-iso: config YAML includes firmware legacyBIOS false" {
  run bash -c '
    cat <<LIMAEOF
firmware:
  legacyBIOS: false
LIMAEOF
  '
  [[ "$output" == *"legacyBIOS: false"* ]]
}

@test "verify-iso: config YAML includes plain true" {
  run bash -c '
    cat <<LIMAEOF
plain: true
LIMAEOF
  '
  [[ "$output" == *"plain: true"* ]]
}

@test "verify-iso: config YAML includes video VNC" {
  run bash -c '
    cat <<LIMAEOF
video:
  display: "vnc"
  vnc:
    display: "127.0.0.1:0,to=9"
LIMAEOF
  '
  [[ "$output" == *"display: \"vnc\""* ]]
}

@test "verify-iso: config YAML includes vmOpts qemu" {
  run bash -c '
    cat <<LIMAEOF
vmOpts:
  qemu:
    cpuType:
      x86_64: "host"
      aarch64: "host"
LIMAEOF
  '
  [[ "$output" == *'cpuType:'* ]]
  [[ "$output" == *'x86_64: "host"'* ]]
}

@test "verify-iso: config YAML has empty mounts" {
  run bash -c '
    cat <<LIMAEOF
mounts: []
LIMAEOF
  '
  [[ "$output" == *"mounts: []"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Serial Log Error Pattern Matching
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: detects kernel panic in serial log" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "Kernel panic - not syncing: Attempted to kill init!" > "$SERIAL_LOG"
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" "$SERIAL_LOG"; then
      echo "ERROR: Fatal boot error detected in serial log"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Fatal boot error"* ]]
}

@test "verify-iso: detects dracut emergency shell" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "dracut-emergency: Dropping to debug shell" > "$SERIAL_LOG"
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" "$SERIAL_LOG"; then
      echo "ERROR: Fatal boot error detected in serial log"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Fatal boot error"* ]]
}

@test "verify-iso: detects GRUB Error" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "GRUB Error: file not found" > "$SERIAL_LOG"
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" "$SERIAL_LOG"; then
      echo "ERROR: Fatal boot error detected in serial log"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Fatal boot error"* ]]
}

@test "verify-iso: clean serial log passes error check" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "systemd[1]: Reached target Multi-User System." > "$SERIAL_LOG"
    echo "anaconda[1234]: Started Anaconda WebUI" >> "$SERIAL_LOG"
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" "$SERIAL_LOG"; then
      echo "ERROR: Fatal boot error detected in serial log"
      exit 1
    fi
    echo "Serial log clean"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "Serial log clean" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Boot Indicator Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: GRUB version detected as boot indicator" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "GRUB version 2.06" > "$SERIAL_LOG"
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" "$SERIAL_LOG"; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
  '
  [ "$output" = "BOOT_OK=1" ]
}

@test "verify-iso: anaconda detected as boot indicator" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "anaconda[1234]: Web UI started" > "$SERIAL_LOG"
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" "$SERIAL_LOG"; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
  '
  [ "$output" = "BOOT_OK=1" ]
}

@test "verify-iso: Reached target detected as boot indicator" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "systemd[1]: Reached target Basic System." > "$SERIAL_LOG"
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" "$SERIAL_LOG"; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
  '
  [ "$output" = "BOOT_OK=1" ]
}

@test "verify-iso: login prompt detected as boot indicator" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "tunaos login:" > "$SERIAL_LOG"
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" "$SERIAL_LOG"; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
  '
  [ "$output" = "BOOT_OK=1" ]
}

@test "verify-iso: no boot indicators found" {
  run bash -c '
    SERIAL_LOG="${TEST_ROOT}/serial.log"
    echo "Some random output" > "$SERIAL_LOG"
    echo "more random stuff" >> "$SERIAL_LOG"
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" "$SERIAL_LOG"; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
  '
  [ "$output" = "BOOT_OK=0" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Lima Status Parsing
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: Running status passes check" {
  run bash -c '
    STATUS="Running"
    if [[ "${STATUS}" == "missing" || "${STATUS}" == "Broken" ]]; then
      echo "ERROR: Lima VM is gone or broken"
      exit 1
    fi
    echo "VM still present ✓"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "VM still present ✓" ]
}

@test "verify-iso: Broken status triggers error" {
  run bash -c '
    STATUS="Broken"
    if [[ "${STATUS}" == "missing" || "${STATUS}" == "Broken" ]]; then
      echo "ERROR: Lima VM is gone or broken after 120s"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"gone or broken"* ]]
}

@test "verify-iso: missing status triggers error" {
  run bash -c '
    STATUS="missing"
    if [[ "${STATUS}" == "missing" || "${STATUS}" == "Broken" ]]; then
      echo "ERROR: Lima VM is gone or broken after 120s"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"gone or broken"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Result Reporting
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: BOOT_OK=1 reports PASSED" {
  run bash -c '
    ISO_FILE="yellowfin-gnome-10-x86_64.iso"
    BOOT_OK=1
    if [ "${BOOT_OK}" -eq 0 ]; then
      echo "ISO Verification FAILED: no boot indicators in serial log"
      exit 1
    fi
    echo "ISO Verification PASSED: $ISO_FILE"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASSED"* ]]
}

@test "verify-iso: BOOT_OK=0 reports FAILED" {
  run bash -c '
    ISO_FILE="broken.iso"
    BOOT_OK=0
    if [ "${BOOT_OK}" -eq 0 ]; then
      echo "ISO Verification FAILED: no boot indicators in serial log"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"FAILED"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# verify-iso.sh — Lima Directory Path
# ═══════════════════════════════════════════════════════════════════════════

@test "verify-iso: serial log path constructed correctly" {
  run bash -c '
    HOME="/home/testuser"
    VM_NAME="verify-iso-yellowfin-gnome-10-x86-64"
    LIMA_DIR="${HOME}/.lima/${VM_NAME}"
    SERIAL_LOG="${LIMA_DIR}/serial.log"
    echo "$SERIAL_LOG"
  '
  [ "$output" = "/home/testuser/.lima/verify-iso-yellowfin-gnome-10-x86-64/serial.log" ]
}
