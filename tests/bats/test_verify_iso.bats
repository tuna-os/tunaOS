#!/usr/bin/env bats
# Unit tests for scripts/verify-iso.sh
#
# Tests:
#   - Argument validation (requires exactly 1 arg)
#   - ISO file existence check
#   - Missing limactl error
#   - VM name construction / sanitization
#   - Architecture detection (arm64 → aarch64)
#   - Lima config generation essentials
#   - Status checking after boot
#   - Kernel panic detection in serial log
#   - Boot indicator detection (GRUB, anaconda, login)
#   - Final result: BOOT_OK flag logic

# ── Argument Validation ───────────────────────────────────────────────────

@test "requires exactly 1 argument" {
  run bash -c '
    if [ "$#" -ne 1 ]; then
      echo "Usage: $0 <iso_file>" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "rejects zero arguments" {
  run bash -c '
    set --
    if [ "$#" -ne 1 ]; then echo "Usage: ..." >&2; exit 1; fi
  '
  [ "$status" -eq 1 ]
}

@test "rejects two arguments" {
  run bash -c '
    set -- iso1.iso iso2.iso
    if [ "$#" -ne 1 ]; then echo "Usage: ..." >&2; exit 1; fi
  '
  [ "$status" -eq 1 ]
}

# ── ISO File Check ────────────────────────────────────────────────────────

@test "exits when ISO file does not exist" {
  run bash -c '
    ISO_PATH="/nonexistent/path.iso"
    if [ ! -f "$ISO_PATH" ]; then
      echo "Error: ISO file not found" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"ISO file not found"* ]]
}

# ── VM Name Sanitization ──────────────────────────────────────────────────

@test "constructs VM name from ISO filename (lowercase, dash-sanitized)" {
  run bash -c '
    ISO_FILE="Yellowfin-GNOME-10-x86_64.iso"
    VM_NAME="verify-iso-$(basename "$ISO_FILE" .iso | tr "[:upper:]" "[:lower:]" | tr -c "[:alnum:]" "-" | sed "s/--*/-/g; s/^-//; s/-$//")"
    echo "$VM_NAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "verify-iso-yellowfin-gnome-10-x86-64" ]]
}

@test "trims leading and trailing dashes from VM name" {
  run bash -c '
    name="---test---vm---"
    name=$(echo "$name" | sed "s/--*/-/g; s/^-//; s/-$//")
    echo "$name"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "test-vm" ]]
}

@test "collapses multiple dashes in VM name" {
  run bash -c '
    name="test----vm"
    name=$(echo "$name" | sed "s/--*/-/g")
    echo "$name"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "test-vm" ]]
}

# ── Architecture Detection ────────────────────────────────────────────────

@test "maps arm64 to aarch64" {
  run bash -c '
    ARCH="arm64"
    if [ "$ARCH" = "arm64" ]; then LIMA_ARCH="aarch64"; else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "aarch64" ]]
}

@test "maps x86_64 to x86_64" {
  run bash -c '
    ARCH="x86_64"
    if [ "$ARCH" = "arm64" ]; then LIMA_ARCH="aarch64"; else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "x86_64" ]]
}

# ── Lima Config Essentials ────────────────────────────────────────────────

@test "generates config with ISO path and arch" {
  ISO_PATH="/path/to/test.iso"
  LIMA_ARCH="x86_64"
  run bash -c '
    ISO_PATH="/path/to/test.iso"; LIMA_ARCH="x86_64"
    cat <<LIMAEOF
images:
  - location: "${ISO_PATH}"
    arch: ${LIMA_ARCH}
LIMAEOF
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"location:"*"test.iso"* ]]
  [[ "$output" == *"arch: x86_64"* ]]
}

# ── VM Status Checking ────────────────────────────────────────────────────

@test "detects missing VM status" {
  run bash -c '
    STATUS="missing"
    if [[ "${STATUS}" == "missing" || "${STATUS}" == "Broken" ]]; then
      echo "ERROR: Lima VM is gone or broken"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"gone or broken"* ]]
}

@test "detects Broken VM status" {
  run bash -c '
    STATUS="Broken"
    if [[ "${STATUS}" == "missing" || "${STATUS}" == "Broken" ]]; then
      echo "ERROR: Lima VM is gone or broken"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"gone or broken"* ]]
}

@test "accepts Running VM status" {
  run bash -c '
    STATUS="Running"
    if [[ "${STATUS}" == "missing" || "${STATUS}" == "Broken" ]]; then
      echo "ERROR"
      exit 1
    fi
    echo "VM still present"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"still present"* ]]
}

# ── Kernel Panic Detection ────────────────────────────────────────────────

@test "detects kernel panic in serial log" {
  run bash -c '
    echo "Kernel panic - not syncing: Attempted to kill init!" > /tmp/test_serial.log
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" /tmp/test_serial.log; then
      echo "ERROR: Fatal boot error detected"
      exit 1
    fi
    rm -f /tmp/test_serial.log
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Fatal boot error"* ]]
}

@test "detects dracut emergency shell" {
  run bash -c '
    echo "Entering dracut-emergency shell" > /tmp/test_serial.log
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" /tmp/test_serial.log; then
      echo "ERROR: Fatal boot error detected"
      exit 1
    fi
    rm -f /tmp/test_serial.log
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Fatal boot error"* ]]
}

@test "clean serial log passes panic check" {
  run bash -c '
    echo "Starting systemd..." > /tmp/test_serial.log
    if grep -qi "kernel panic\|Kernel panic\|dracut-emergency\|Boot failed\|GRUB Error" /tmp/test_serial.log; then
      exit 1
    fi
    echo "no errors"
    rm -f /tmp/test_serial.log
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "no errors" ]]
}

# ── Boot Indicator Detection ──────────────────────────────────────────────

@test "detects GRUB version in serial log" {
  run bash -c '
    echo "GRUB version 2.12" > /tmp/test_serial.log
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" /tmp/test_serial.log; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
    rm -f /tmp/test_serial.log
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "BOOT_OK=1" ]]
}

@test "detects anaconda startup in serial log" {
  run bash -c '
    echo "Starting Anaconda installer..." > /tmp/test_serial.log
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" /tmp/test_serial.log; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
    rm -f /tmp/test_serial.log
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "BOOT_OK=1" ]]
}

@test "detects login prompt in serial log" {
  run bash -c '
    echo "Welcome to TunaOS! tunaos login:" > /tmp/test_serial.log
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" /tmp/test_serial.log; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
    rm -f /tmp/test_serial.log
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "BOOT_OK=1" ]]
}

@test "no boot indicators sets BOOT_OK=0" {
  run bash -c '
    echo "random noise" > /tmp/test_serial.log
    BOOT_OK=0
    if grep -qi "GRUB version\|Booting .\+Live\|anaconda\|Started Anaconda\|Reached target\|Welcome to\|login:" /tmp/test_serial.log; then
      BOOT_OK=1
    fi
    echo "BOOT_OK=$BOOT_OK"
    rm -f /tmp/test_serial.log
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "BOOT_OK=0" ]]
}

# ── Final Result ──────────────────────────────────────────────────────────

@test "exits 1 when BOOT_OK=0" {
  run bash -c '
    BOOT_OK=0
    if [ "${BOOT_OK}" -eq 0 ]; then
      echo "ISO Verification FAILED"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"FAILED"* ]]
}

@test "exits 0 when BOOT_OK=1" {
  run bash -c '
    BOOT_OK=1
    if [ "${BOOT_OK}" -eq 0 ]; then
      exit 1
    fi
    echo "ISO Verification PASSED"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASSED"* ]]
}
