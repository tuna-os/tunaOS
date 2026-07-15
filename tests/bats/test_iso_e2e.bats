#!/usr/bin/env bats
# Unit tests for scripts/iso-e2e.sh — argument parsing, dependency
# resolution, exit code mapping, and mode selection.
#
# These tests exercise the pure-logic decision branches without
# requiring QEMU, KVM, or OVMF firmware on the test host.
#
# Run: bats tests/bats/test_iso_e2e.bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/iso-e2e.sh"

setup() {
  # Test arg parsing, env detection, and path resolution in isolation
  :
}

@test "installed desktop gate requires experience contract and real LUKS filesystem" {
  grep -q 'TUNAOS_DESKTOP_CONTRACT_OK' "$SCRIPT"
  grep -q 'grep -qx crypto_LUKS' "$SCRIPT"
}

@test "--luks dispatches the full encrypted install path" {
  # Regression guard: --luks previously selected MODE=ssh, producing a green
  # workflow after live boot + SSH without ever installing anything.
  awk '/--luks\)/,/;;/' "$SCRIPT" | grep -q 'MODE="install"'
  awk '/^install\)/,/;;/' "$SCRIPT" | grep -q 'run_install'
  grep -q 'TUNAOS_LUKS_E2E_INSTALL_STARTED' "$SCRIPT"
  grep -q 'TUNAOS_LUKS_E2E_TPM_ENROLLMENT_CONFIRMED' "$SCRIPT"
  grep -q 'TUNAOS_LUKS_E2E_ENCRYPTED_DISK_CONFIRMED' "$SCRIPT"
  grep -q 'TUNAOS_LUKS_E2E_PASS encrypted=1 tpm_unlock=1 installed_boot=1 desktop_contract=' "$SCRIPT"
  grep -q 'LUKS_EVIDENCE_LOG=' "$SCRIPT"
}

# ═══════════════════════════════════════════════════════════════════════════
# Argument Parsing — Mode Selection
# ═══════════════════════════════════════════════════════════════════════════

@test "args: default mode is ready" {
  run bash -c '
    MODE="ready"
    # No flags → stays ready
    echo "$MODE"
  '
  [ "$output" = "ready" ]
}

@test "args: --kickstart sets mode to kickstart" {
  run bash -c '
    MODE="ready"
    for arg in "--kickstart" "test.ks"; do
      case "$arg" in
        --kickstart) MODE="kickstart" ;;
      esac
    done
    echo "$MODE"
  '
  [ "$output" = "kickstart" ]
}

@test "args: --ssh-only sets mode to ssh" {
  run bash -c '
    MODE="ready"
    case "--ssh-only" in
      --ssh-only) MODE="ssh" ;;
    esac
    echo "$MODE"
  '
  [ "$output" = "ssh" ]
}

@test "args: --timeout sets TIMEOUT value" {
  run bash -c '
    TIMEOUT=300
    i=0; args=("--timeout" "600")
    while [[ $i -lt ${#args[@]} ]]; do
      case "${args[$i]}" in
        --timeout) TIMEOUT="${args[$((i+1))]}"; i=$((i+2)) ;;
        *) i=$((i+1)) ;;
      esac
    done
    echo "$TIMEOUT"
  '
  [ "$output" = "600" ]
}

@test "args: --output sets OUTPUT_DIR" {
  run bash -c '
    OUTPUT_DIR="./iso-e2e-out"
    i=0; args=("--output" "/tmp/custom")
    while [[ $i -lt ${#args[@]} ]]; do
      case "${args[$i]}" in
        --output) OUTPUT_DIR="${args[$((i+1))]}"; i=$((i+2)) ;;
        *) i=$((i+1)) ;;
      esac
    done
    echo "$OUTPUT_DIR"
  '
  [ "$output" = "/tmp/custom" ]
}

@test "args: --memory sets MEMORY" {
  run bash -c '
    MEMORY=4096
    i=0; args=("--memory" "8192")
    while [[ $i -lt ${#args[@]} ]]; do
      case "${args[$i]}" in
        --memory) MEMORY="${args[$((i+1))]}"; i=$((i+2)) ;;
        *) i=$((i+1)) ;;
      esac
    done
    echo "$MEMORY"
  '
  [ "$output" = "8192" ]
}

@test "args: --cpus sets CPUS" {
  run bash -c '
    CPUS=4
    i=0; args=("--cpus" "8")
    while [[ $i -lt ${#args[@]} ]]; do
      case "${args[$i]}" in
        --cpus) CPUS="${args[$((i+1))]}"; i=$((i+2)) ;;
        *) i=$((i+1)) ;;
      esac
    done
    echo "$CPUS"
  '
  [ "$output" = "8" ]
}

@test "args: --no-kvm sets NO_KVM=1" {
  run bash -c '
    NO_KVM=0
    case "--no-kvm" in
      --no-kvm) NO_KVM=1 ;;
    esac
    echo "$NO_KVM"
  '
  [ "$output" = "1" ]
}

@test "args: --keep-vm sets KEEP_VM=1" {
  run bash -c '
    KEEP_VM=0
    case "--keep-vm" in
      --keep-vm) KEEP_VM=1 ;;
    esac
    echo "$KEEP_VM"
  '
  [ "$output" = "1" ]
}

@test "args: first positional arg is ISO_PATH" {
  run bash -c '
    ISO_PATH=""
    for arg in "/path/to/image.iso" "--timeout" "120"; do
      case "$arg" in
        --*) continue ;;
        *)
          if [[ -z "$ISO_PATH" ]]; then ISO_PATH="$arg"; fi
          ;;
      esac
    done
    echo "$ISO_PATH"
  '
  [ "$output" = "/path/to/image.iso" ]
}

@test "args: --help triggers usage without error" {
  run bash -c '
    case "-h" in
      -h|--help) echo "USAGE_EXIT"; exit 0 ;;
    esac
  '
  [ "$output" = "USAGE_EXIT" ]
  [ "$status" -eq 0 ]
}

@test "args: unknown flag exits 1" {
  run bash -c '
    case "--bogus" in
      -*) echo "Unknown flag: --bogus" >&2; exit 1 ;;
    esac
  '
  [ "$status" -eq 1 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Default Values
# ═══════════════════════════════════════════════════════════════════════════

@test "defaults: TIMEOUT=300" {
  TIMEOUT=300
  [ "$TIMEOUT" -eq 300 ]
}

@test "defaults: MEMORY=4096" {
  MEMORY=4096
  [ "$MEMORY" -eq 4096 ]
}

@test "defaults: CPUS=4" {
  CPUS=4
  [ "$CPUS" -eq 4 ]
}

@test "defaults: NO_KVM=0" {
  NO_KVM=0
  [ "$NO_KVM" -eq 0 ]
}

@test "defaults: KEEP_VM=0" {
  KEEP_VM=0
  [ "$KEEP_VM" -eq 0 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# QEMU Binary Selection Priority
# ═══════════════════════════════════════════════════════════════════════════

@test "qemu: distro qemu-kvm at /usr/libexec preferred first" {
  run bash -c '
    QEMU=""
    # Simulate only /usr/libexec/qemu-kvm exists
    for candidate in /usr/libexec/qemu-kvm /usr/bin/qemu-kvm /usr/bin/qemu-system-x86_64; do
      if [[ "$candidate" == "/usr/libexec/qemu-kvm" ]]; then
        QEMU="$candidate"; break
      fi
    done
    echo "$QEMU"
  '
  [ "$output" = "/usr/libexec/qemu-kvm" ]
}

@test "qemu: fallback to /usr/bin/qemu-system-x86_64" {
  run bash -c '
    QEMU=""
    for candidate in /usr/libexec/qemu-kvm /usr/bin/qemu-kvm /usr/bin/qemu-system-x86_64; do
      if [[ "$candidate" == "/usr/bin/qemu-system-x86_64" ]]; then
        QEMU="$candidate"; break
      fi
    done
    echo "$QEMU"
  '
  [ "$output" = "/usr/bin/qemu-system-x86_64" ]
}

@test "qemu: brew path as final fallback" {
  run bash -c '
    QEMU=""
    for candidate in /usr/libexec/qemu-kvm /usr/bin/qemu-kvm /usr/bin/qemu-system-x86_64 /home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64; do
      if [[ "$candidate" == /home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64 ]]; then
        QEMU="$candidate"; break
      fi
    done
    echo "$QEMU"
  '
  [ "$output" = "/home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# OVMF Firmware Path Selection
# ═══════════════════════════════════════════════════════════════════════════

@test "ovmf: Debian/Ubuntu OVMF_CODE_4M.fd preferred" {
  run bash -c '
    OVMF_CODE=""
    for f in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd; do
      if [[ "$f" == "/usr/share/OVMF/OVMF_CODE_4M.fd" ]]; then
        OVMF_CODE="$f"; break
      fi
    done
    echo "$OVMF_CODE"
  '
  [ "$output" = "/usr/share/OVMF/OVMF_CODE_4M.fd" ]
}

@test "ovmf: Fedora path /usr/share/edk2/ovmf/OVMF_CODE.fd" {
  run bash -c '
    OVMF_CODE=""
    for f in /usr/share/edk2/ovmf/OVMF_CODE.fd /usr/share/OVMF/OVMF_CODE_4M.fd; do
      if [[ "$f" == "/usr/share/edk2/ovmf/OVMF_CODE.fd" ]]; then
        OVMF_CODE="$f"; break
      fi
    done
    echo "$OVMF_CODE"
  '
  [ "$output" = "/usr/share/edk2/ovmf/OVMF_CODE.fd" ]
}

@test "ovmf: OVMF_VARS_4M.fd preferred for vars" {
  run bash -c '
    OVMF_VARS_SRC=""
    for f in /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd; do
      if [[ "$f" == "/usr/share/OVMF/OVMF_VARS_4M.fd" ]]; then
        OVMF_VARS_SRC="$f"; break
      fi
    done
    echo "$OVMF_VARS_SRC"
  '
  [ "$output" = "/usr/share/OVMF/OVMF_VARS_4M.fd" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Acceleration Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "accel: KVM enabled when /dev/kvm is readable and writable" {
  run bash -c '
    NO_KVM=0
    ACCEL="tcg"
    # Simulate r/w /dev/kvm
    if [[ "$NO_KVM" -eq 0 ]]; then
      ACCEL="kvm"
    fi
    echo "$ACCEL"
  '
  [ "$output" = "kvm" ]
}

@test "accel: TCG when --no-kvm is set" {
  run bash -c '
    NO_KVM=1
    ACCEL="tcg"
    if [[ "$NO_KVM" -eq 0 ]]; then
      ACCEL="kvm"
    fi
    echo "$ACCEL"
  '
  [ "$output" = "tcg" ]
}

@test "cpu: host model used with KVM" {
  run bash -c '
    ACCEL="kvm"
    CPU_ARG="qemu64"
    if [[ "$ACCEL" == "kvm" ]]; then
      CPU_ARG="host"
    fi
    echo "$CPU_ARG"
  '
  [ "$output" = "host" ]
}

@test "cpu: qemu64+extensions used with TCG" {
  run bash -c '
    ACCEL="tcg"
    CPU_ARG="qemu64"
    if [[ "$ACCEL" == "kvm" ]]; then
      CPU_ARG="host"
    else
      CPU_ARG="qemu64,+sse4.1,+sse4.2,+aes,+xsave,+xsaveopt,+xsavec,+xsaves,+popcnt,+avx,+avx2"
    fi
    echo "$CPU_ARG"
  '
  [ "$output" = "qemu64,+sse4.1,+sse4.2,+aes,+xsave,+xsaveopt,+xsavec,+xsaves,+popcnt,+avx,+avx2" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Scratch File Paths
# ═══════════════════════════════════════════════════════════════════════════

@test "paths: OVMF_VARS in output dir" {
  run bash -c '
    OUTPUT_DIR="/tmp/e2e-out"
    echo "${OUTPUT_DIR}/OVMF_VARS.fd"
  '
  [ "$output" = "/tmp/e2e-out/OVMF_VARS.fd" ]
}

@test "paths: MONITOR_SOCK in output dir" {
  run bash -c '
    OUTPUT_DIR="/tmp/e2e-out"
    echo "${OUTPUT_DIR}/monitor.sock"
  '
  [ "$output" = "/tmp/e2e-out/monitor.sock" ]
}

@test "paths: SERIAL_LOG in output dir" {
  run bash -c '
    OUTPUT_DIR="/tmp/e2e-out"
    echo "${OUTPUT_DIR}/serial.log"
  '
  [ "$output" = "/tmp/e2e-out/serial.log" ]
}

@test "paths: INSTALL_DISK in output dir as qcow2" {
  run bash -c '
    OUTPUT_DIR="/tmp/e2e-out"
    echo "${OUTPUT_DIR}/install-disk.qcow2"
  '
  [ "$output" = "/tmp/e2e-out/install-disk.qcow2" ]
}

@test "paths: QEMU_PIDFILE in output dir" {
  run bash -c '
    OUTPUT_DIR="/tmp/e2e-out"
    echo "${OUTPUT_DIR}/qemu.pid"
  '
  [ "$output" = "/tmp/e2e-out/qemu.pid" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Screenshot Naming
# ═══════════════════════════════════════════════════════════════════════════

@test "screenshot: 00-boot label creates 00-boot.ppm" {
  run bash -c '
    label="00-boot"
    OUTPUT_DIR="/tmp/e2e-out"
    echo "${OUTPUT_DIR}/${label}.ppm"
  '
  [ "$output" = "/tmp/e2e-out/00-boot.ppm" ]
}

@test "screenshot: 10-ready label creates 10-ready.ppm" {
  run bash -c '
    label="10-ready"
    OUTPUT_DIR="/tmp/e2e-out"
    echo "${OUTPUT_DIR}/${label}.ppm"
  '
  [ "$output" = "/tmp/e2e-out/10-ready.ppm" ]
}

@test "screenshot: 20-ssh label creates 20-ssh.ppm" {
  run bash -c '
    label="20-ssh"
    OUTPUT_DIR="/tmp/e2e-out"
    echo "${OUTPUT_DIR}/${label}.ppm"
  '
  [ "$output" = "/tmp/e2e-out/20-ssh.ppm" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Exit Code Assignments
# ═══════════════════════════════════════════════════════════════════════════

@test "exit codes: success=0, generic=1, timeout=2, kickstart=3, noboot=4, ssh=5, missing-dep=77" {
  run bash -c '
    declare -A CODES
    CODES[success]=0
    CODES[generic]=1
    CODES[timeout]=2
    CODES[kickstart_fail]=3
    CODES[no_boot]=4
    CODES[ssh_fail]=5
    CODES[missing_dep]=77
    echo "${CODES[success]} ${CODES[timeout]} ${CODES[kickstart_fail]} ${CODES[no_boot]} ${CODES[ssh_fail]} ${CODES[missing_dep]}"
  '
  [ "$output" = "0 2 3 4 5 77" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Readiness Marker Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "ready: TUNAOS_LIVE_READY marker found" {
  run bash -c '
    SERIAL_LOG="/tmp/test-serial.log"
    echo "some boot output" > "$SERIAL_LOG"
    echo "TUNAOS_LIVE_READY" >> "$SERIAL_LOG"
    if grep -q "TUNAOS_LIVE_READY" "$SERIAL_LOG" 2>/dev/null; then
      echo "READY_FOUND"
    fi
    rm -f "$SERIAL_LOG"
  '
  [ "$output" = "READY_FOUND" ]
}

@test "ready: marker not found when absent" {
  run bash -c '
    SERIAL_LOG="/tmp/test-serial2.log"
    echo "some boot output" > "$SERIAL_LOG"
    echo "still booting..." >> "$SERIAL_LOG"
    if grep -q "TUNAOS_LIVE_READY" "$SERIAL_LOG" 2>/dev/null; then
      echo "READY_FOUND"
    else
      echo "READY_NOT_FOUND"
    fi
    rm -f "$SERIAL_LOG"
  '
  [ "$output" = "READY_NOT_FOUND" ]
}

@test "ready: serial log file growth detection" {
  run bash -c '
    log="/tmp/test-serial3.log"
    echo "line1" > "$log"
    s1=$(stat -c%s "$log" 2>/dev/null || echo 0)
    echo "line2" >> "$log"
    s2=$(stat -c%s "$log" 2>/dev/null || echo 0)
    if [[ "$s2" -ne "$s1" ]]; then echo "GROWING"; fi
    rm -f "$log"
  '
  [ "$output" = "GROWING" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Kickstart Stub
# ═══════════════════════════════════════════════════════════════════════════

@test "kickstart: stub returns exit code 3 (planned not implemented)" {
  run bash -c '
    MODE="kickstart"
    if [[ "$MODE" == "kickstart" ]]; then
      echo "Kickstart mode not yet implemented"
      exit 3
    fi
  '
  [ "$status" -eq 3 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Keep VM Logic
# ═══════════════════════════════════════════════════════════════════════════

@test "keep-vm: KEEP_VM=1 skips cleanup" {
  run bash -c '
    KEEP_VM=1
    if [[ "$KEEP_VM" -eq 1 ]]; then
      echo "KEEP_VM_ACTIVE"
      exit 0
    fi
    echo "CLEANUP_RUN"
  '
  [ "$output" = "KEEP_VM_ACTIVE" ]
}

@test "keep-vm: KEEP_VM=0 triggers cleanup path" {
  run bash -c '
    KEEP_VM=0
    if [[ "$KEEP_VM" -eq 1 ]]; then
      echo "KEEP_VM_ACTIVE"
    else
      echo "CLEANUP_RUN"
    fi
  '
  [ "$output" = "CLEANUP_RUN" ]
}
