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
  # e9fe9e5: the gate deliberately accepts OK or FAIL — either proves the
  # contract service ran, i.e. graphical.target was reached and the DM started.
  grep -qF 'TUNAOS_DESKTOP_CONTRACT_(OK|FAIL)' "$SCRIPT"
  grep -q 'crypto_LUKS' "$SCRIPT"
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
  grep -q 'mv -f "$SERIAL_LOG" "$LIVE_SERIAL_LOG"' "$SCRIPT"
}

@test "run_install uploads and runs the TAP-style LUKS check script over SSH" {
  grep -q 'scripts/e2e-luks-checks.sh\|e2e-luks-checks.sh' "$SCRIPT"
  grep -q 'lib/e2e-assert.sh' "$SCRIPT"
}

@test "e2e-assert.sh check() records pass and fail correctly" {
  run bash -c "source '${REPO_ROOT}/scripts/lib/e2e-assert.sh'; check 'true succeeds' true; check 'false fails' false; echo PASS=\$PASS FAIL=\$FAIL"
  [[ "$output" == *"ok - true succeeds"* ]]
  [[ "$output" == *"not ok - false fails"* ]]
  [[ "$output" == *"PASS=1 FAIL=1"* ]]
}

@test "e2e-assert.sh print_summary exits with the failure count" {
  run bash -c "source '${REPO_ROOT}/scripts/lib/e2e-assert.sh'; check 'ok one' true; check 'bad one' false; check 'bad two' false; print_summary"
  [ "$status" -eq 2 ]
  [[ "$output" == *"# Results: 1 passed, 2 failed, 3 total"* ]]
}

setup_luks_check_stubs() {
  mkdir -p "${BATS_TEST_TMPDIR}/bin"
  printf '#!/bin/bash\nshift\nexec "$@"\n' >"${BATS_TEST_TMPDIR}/bin/sudo"
  printf '#!/bin/bash\necho "/dev/vda1 vfat"\n' >"${BATS_TEST_TMPDIR}/bin/lsblk"
  chmod +x "${BATS_TEST_TMPDIR}/bin/sudo" "${BATS_TEST_TMPDIR}/bin/lsblk"
}

@test "e2e-luks-checks.sh reports failure cleanly when no LUKS partition exists" {
  # Simulate the guest environment: stub sudo/lsblk so no crypto_LUKS line is
  # ever produced, and confirm the script degrades to a clean failing summary
  # instead of erroring out on unset variables (set -u) or unbound sudo.
  setup_luks_check_stubs
  PATH="${BATS_TEST_TMPDIR}/bin:${PATH}" TEST_LIB_DIR="${REPO_ROOT}/scripts/lib" \
    run bash "${REPO_ROOT}/scripts/e2e-luks-checks.sh"
  [ "$status" -eq 2 ]
  [[ "$output" == *"not ok - installed disk has a crypto_LUKS partition"* ]]
  [[ "$output" == *"not ok - LUKS header has a systemd-tpm2 enrollment token"* ]]
}

@test "run_install and ssh mode upload and run the smoke check script" {
  grep -q 'e2e-smoke-checks.sh' "$SCRIPT"
  grep -q 'run_smoke_checks' "$SCRIPT"
  # ssh mode gates on the smoke checks; install mode runs them pre-install.
  awk '/^ssh\)/,/;;/' "$SCRIPT" | grep -q 'run_smoke_checks'
  awk '/^run_install\(\)/,/^}/' "$SCRIPT" | grep -q 'run_smoke_checks'
}

setup_smoke_check_stubs() {
  # Exported-function stubs (not files): BATS_TEST_TMPDIR can live on a
  # noexec /tmp, where file stubs silently fail to exec. Exported functions
  # propagate into the `bash script` child and win over PATH lookups.
  sudo() { "$@"; }
  systemctl() {
    case "$1" in
      is-system-running) echo degraded ;;
      is-active) echo active ;;
      --failed) : ;;
    esac
    return 0
  }
  bootc() {
    [[ "${1:-}" == "status" && "${2:-}" == "--json" ]] && echo '{"image": "ghcr.io/tuna-os/x:y"}'
    return 0
  }
  curl() { return 0; }
  getent() { echo "140.82.112.3 ghcr.io"; }
  rpm() { seq 200; }
  locale() { return 0; }
  hostname() { echo testhost; }
  export -f sudo systemctl bootc curl getent rpm locale hostname
}

@test "e2e-smoke-checks.sh passes with a healthy stubbed guest" {
  setup_smoke_check_stubs
  TEST_LIB_DIR="${REPO_ROOT}/scripts/lib" \
    run bash "${REPO_ROOT}/scripts/e2e-smoke-checks.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ok - system has booted (running or degraded)"* ]]
  [[ "$output" == *"ok - bootc status succeeds"* ]]
  [[ "$output" == *"ok - package metadata intact (>100 installed packages)"* ]]
  [[ "$output" == *"# Results: "* ]]
  [[ "$output" != *"not ok - "* ]]
}

@test "e2e-smoke-checks.sh exit code equals its failure count" {
  setup_smoke_check_stubs
  # Break two checks: dead network manager/sshd (is-active fails) — the
  # script must keep going (no set -e abort) and exit with the exact count.
  systemctl() {
    case "$1" in
      is-system-running) echo degraded; return 0 ;;
      is-active) return 1 ;;
    esac
    return 0
  }
  export -f systemctl
  TEST_LIB_DIR="${REPO_ROOT}/scripts/lib" \
    run bash "${REPO_ROOT}/scripts/e2e-smoke-checks.sh"
  [ "$status" -eq 2 ]
  [[ "$output" == *"not ok - ssh daemon is active"* ]]
  [[ "$output" == *"not ok - a network manager is active"* ]]
}

setup_runtime_check_stubs() {
  # Exported-function stubs simulating a healthy installed bootc guest for
  # build_scripts/checks/e2e-runtime-checks.sh (which is self-contained — it runs
  # from /usr/libexec inside the image, so it sources nothing).
  systemctl() {
    case "$1" in
      is-system-running) echo running ;;
      is-active) echo active ;;
      show) echo "gdm.service" ;;
      list-unit-files) : ;; # no sshd shipped -> host-key check skipped
      --failed) : ;;
    esac
    return 0
  }
  findmnt() { echo overlay; return 0; }
  bootc() { echo 'Image: ghcr.io/tuna-os/x:y'; return 0; }
  systemd-analyze() { return 0; }
  rpm() { seq 200; }
  locale() { return 0; }
  hostname() { echo tunaos-e2e; }
  export -f systemctl findmnt bootc systemd-analyze rpm locale hostname
}

@test "e2e-runtime-checks.sh passes with a healthy installed guest and emits markers" {
  setup_runtime_check_stubs
  run bash "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh" gnome
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_INSTALL_CHECKS_BEGIN desktop=gnome"* ]]
  [[ "$output" == *"ok - display manager matches gnome contract"* ]]
  [[ "$output" == *"ok - root filesystem is immutable (ro or composefs/overlay)"* ]]
  [[ "$output" == *"TUNAOS_INSTALL_CHECKS_RESULT pass="* ]]
  [[ "$output" == *" fail=0 desktop=gnome"* ]]
  [[ "$output" != *"not ok - "* ]]
}

@test "e2e-runtime-checks.sh counts failures and rejects a wrong display manager" {
  setup_runtime_check_stubs
  # sddm answering for a gnome image must fail the DM contract check.
  systemctl() {
    case "$1" in
      is-system-running) echo running ;;
      is-active) echo active ;;
      show) echo "sddm.service" ;;
      list-unit-files) : ;;
      --failed) : ;;
    esac
    return 0
  }
  export -f systemctl
  run bash "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh" gnome
  [ "$status" -eq 1 ]
  [[ "$output" == *"not ok - display manager matches gnome contract"* ]]
  [[ "$output" == *" fail=1 desktop=gnome"* ]]
}

@test "installed-stage harvest gates on the serial TAP markers" {
  # harvest_install_checks reads the markers e2e-runtime-checks emits on
  # ttyS0, and must be wired into both the install path and the disk gate.
  grep -q 'harvest_install_checks()' "$SCRIPT"
  grep -q 'TUNAOS_INSTALL_CHECKS_RESULT' "$SCRIPT"
  # run_install's body contains a column-0 '}' inside the recipe heredoc, so
  # awk function-range extraction truncates early; grep the exact call sites.
  grep -qF 'harvest_install_checks || return 1' "$SCRIPT"   # install path
  grep -qF 'harvest_install_checks || rc=1' "$SCRIPT"       # disk gate
}

@test "app-launch mode supports per-DE matrices with session env" {
  # openQA apps_startstop clone: "auto" resolves a DE matrix from FLAVOR,
  # launches inside the live session (bus + compositor env), and exits with
  # the aggregate VLM failure count.
  # The block contains a nested case (matrix selection) whose ';;' would
  # truncate an awk /;;/ range — anchor on the block's final exit instead.
  awk '/^app-launch\)/,/exit "\$app_failures"/' "$SCRIPT" >"${BATS_TEST_TMPDIR}/applaunch"
  grep -q 'org.gnome.Nautilus' "${BATS_TEST_TMPDIR}/applaunch"
  grep -q 'org.kde.dolphin' "${BATS_TEST_TMPDIR}/applaunch"
  grep -q 'com.system76.CosmicFiles' "${BATS_TEST_TMPDIR}/applaunch"
  grep -q 'thunar' "${BATS_TEST_TMPDIR}/applaunch"
  grep -q 'DBUS_SESSION_BUS_ADDRESS' "${BATS_TEST_TMPDIR}/applaunch"
  grep -q 'exit "\$app_failures"' "${BATS_TEST_TMPDIR}/applaunch"
}

@test "harvest_install_checks tolerates absent markers and flags failures" {
  # Extract just the function; INSTALL_CHECKS_WAIT=0 skips the 90s serial wait.
  local fn
  fn=$(awk '/^harvest_install_checks\(\)/,/^}/' "$SCRIPT")
  # Old image: no markers at all -> succeed (old tags must stay promotable).
  run bash -c "SERIAL_LOG=/dev/null INSTALL_CHECKS_WAIT=0; $fn; harvest_install_checks"
  [ "$status" -eq 0 ]
  [[ "$output" == *"predates e2e-runtime-checks"* ]]
  # Failing checks in the serial log -> warn by default, fail under strict.
  local log="${BATS_TEST_TMPDIR}/serial.log"
  printf 'TUNAOS_INSTALL_CHECKS_BEGIN desktop=kde\nnot ok - x\nTUNAOS_INSTALL_CHECKS_RESULT pass=9 fail=1 desktop=kde\n' >"$log"
  run bash -c "SERIAL_LOG='$log' INSTALL_CHECKS_WAIT=0; $fn; harvest_install_checks"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning::installed-system checks reported 1 failure(s)"* ]]
  [[ "$output" == *"not ok - x"* ]]
  run bash -c "SERIAL_LOG='$log' INSTALL_CHECKS_WAIT=0 E2E_SMOKE_STRICT=1; $fn; harvest_install_checks"
  [ "$status" -eq 1 ]
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
# Paint Wait (tunaOS#581)
# ═══════════════════════════════════════════════════════════════════════════
# Under plain virtio-vga the guest paints with llvmpipe, and first paint can
# trail the serial markers by minutes on a 2-4 vCPU runner. The evidence
# screenshot must wait for paint (bounded) instead of a fixed sleep, and must
# never flip a healthy-but-slow boot into a failed gate.

@test "paint-wait: wait_for_paint helper exists and defaults to a 120s cap" {
  grep -q '^wait_for_paint()' "$SCRIPT"
  awk '/^wait_for_paint\(\)/,/^}/' "$SCRIPT" | grep -q 'TBOX_E2E_PAINT_TIMEOUT:-120'
  awk '/^wait_for_paint\(\)/,/^}/' "$SCRIPT" | grep -q 'screenshot_sane'
}

@test "paint-wait: disk-mode gate polls for paint instead of the fixed 30s sleep" {
  # The #581 defect: `sleep 30; screenshot` after the contract marker — GDM
  # under llvmpipe routinely needs longer, so the evidence gallery got black
  # frames for healthy boots. The fixed sleep must be gone from the disk path.
  run bash -c "awk '/^disk\)/,/^;;/' \"$SCRIPT\" | grep -c 'sleep 30'"
  [ "$output" -eq 0 ]
  awk '/^disk\)/,/^;;/' "$SCRIPT" | grep -q 'wait_for_paint "10-ready"'
}

@test "paint-wait: ready mode waits for paint before the 10-ready screenshot" {
  # The screenshot-sanity fallback for serial-less kernels re-measures the
  # same 10-ready file, so waiting for paint here also makes that fallback
  # able to distinguish "slow" from "failed".
  awk '/^ready\)/,/^;;/' "$SCRIPT" | grep -q 'wait_for_paint "10-ready"'
}

@test "paint-wait: the wait is evidence, never a gate — serial markers decide" {
  # A machine that cannot paint must extend the run, not fail it. Both call
  # sites swallow the helper's return.
  run bash -c "grep -c 'wait_for_paint \"10-ready\" || true' \"$SCRIPT\""
  [ "$output" -ge 2 ]
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

@test "ready: default LIVE_MARKER accepts tacklebox's generic TBOX_LIVE_READY" {
  # iso-builder's reference cells (aurora et al.) are built by tacklebox,
  # which is a generic bootc ISO maker and bakes its own neutral marker
  # rather than a tunaOS-branded one. The harness owns the contract, so
  # its default accepts both. The default is EVALUATED out of the script
  # itself so this test fails if the shipped default ever drifts, and the
  # contract value is asserted explicitly so a drift is a failure here
  # rather than a silently weakened assertion.
  local default
  default=$(unset LIVE_MARKER; eval "$(grep '^LIVE_MARKER=' "$SCRIPT")"; echo "$LIVE_MARKER")
  [ "$default" = 'TUNAOS_LIVE_READY|TBOX_LIVE_READY' ]
  SERIAL_LOG="$BATS_TEST_TMPDIR/test-serial3.log"
  echo "some boot output" > "$SERIAL_LOG"
  echo "TBOX_LIVE_READY uptime=12.3" >> "$SERIAL_LOG"
  grep -qE -- "$default" "$SERIAL_LOG"
  echo "still booting" > "$SERIAL_LOG"
  ! grep -qE -- "$default" "$SERIAL_LOG"
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

@test "serial: every QEMU boot opens the console log in append mode" {
  # `-serial file:PATH` truncates and then writes at QEMU's own offset, so
  # once run_install tees ssh output into the same file, later console writes
  # overwrite the transcript (and vice versa). That silently destroyed the
  # guest console for the whole install window in run 30729902967, the one
  # place an OOM report or hung-task splat would have been. Keep every boot
  # on the shared append-mode chardev.
  grep -q 'append=on' "$SCRIPT"
  ! grep -q -- '-serial "file:${SERIAL_LOG}"' "$SCRIPT"
  # live boot, fisherman installed boot, TPM auto-unlock verify boot,
  # generic installed boot, --disk boot
  [ "$(grep -c '"${E2E_SERIAL_ARGS\[@\]}"' "$SCRIPT")" -eq 5 ]
}

@test "install: a console heartbeat outlives the ssh channel" {
  # The install phase is where the guest can stop answering while QEMU stays
  # up. The heartbeat reports memory/disk pressure to /dev/console from a
  # setsid'd process, so evidence survives the ssh session dying.
  grep -q 'TUNAOS_E2E_HEARTBEAT' "$SCRIPT"
  grep -q 'setsid --fork /usr/local/bin/tunaos-e2e-heartbeat' "$SCRIPT"
  grep -q 'pkill -f tunaos-e2e-heartbeat' "$SCRIPT"
  # Swap exhaustion is the other half of the diagnosis, so the heartbeat has
  # to report it alongside MemAvailable.
  grep -q 'swapfree_kb' "$SCRIPT"
}

@test "install: the live guest gets a swap disk, addressed by serial" {
  # podman's copy of the exported OCI layout into the install-time scratch
  # store allocates on the order of the image size. With no swap the kernel
  # can only kill it: run 30730744132 lost podman at anon-rss 7147396kB on
  # an 8192 MiB guest. The swap disk is attached to the install boot and
  # addressed by /dev/disk/by-id, never /dev/vdX, because the recipe installs to
  # /dev/vda and the two must never be confused.
  grep -q 'SWAP_DISK="${OUTPUT_DIR}/swap-disk.qcow2"' "$SCRIPT"
  grep -q 'qemu-img create -f qcow2 "\$SWAP_DISK" 8G' "$SCRIPT"
  grep -q 'serial=${SWAP_DISK_SERIAL}' "$SCRIPT"
  grep -q 'SWAP_DISK_BYID="/dev/disk/by-id/virtio-${SWAP_DISK_SERIAL}"' "$SCRIPT"
  grep -q "mkswap -L tunaos-e2e-swap" "$SCRIPT"
  grep -q "swapon \${SWAP_DISK_BYID}" "$SCRIPT"
  # Install boot only: the installed system must never see it (no fstab
  # entry, no dangling swap device on the post-install boots).
  [ "$(grep -c 'drive=swapdisk' "$SCRIPT")" -eq 1 ]
}

@test "installed boot: the disk is pinned first in the firmware boot order" {
  # The live-ISO boot and the installed boot share one OVMF_VARS file, so the
  # installed boot inherits OVMF's "EFI Internal Shell" NVRAM entry. Variants
  # whose install writes its own EFI variable (efibootmgr prepends) boot
  # anyway; sailfin's composefs/systemd-boot install cannot write efivars from
  # inside the install container, so its auto-enumerated disk option lands
  # after the shell and the guest sits at `Shell>` (run 30732193680).
  # bootindex publishes a QEMU fw_cfg boot order OVMF applies over the stale
  # NVRAM. Both post-install boots need it; the live boot must NOT have it
  # (the ISO has to win there).
  # fisherman passphrase gate, TPM auto-unlock verify boot, fisherman
  # installed boot, generic TPM gate
  [ "$(grep -c 'device virtio-blk-pci,drive=disk,bootindex=0' "$SCRIPT")" -eq 4 ]
  grep -q -- '-device virtio-blk-pci,drive=disk \\' "$SCRIPT"
}

@test "installed boot: the ESP is dumped before the install VM is destroyed" {
  # Whether the install produced a bootable disk is only knowable from the
  # ESP, and the ESP is unreachable once the live guest powers off. Dump it
  # while the BLS kargs are being appended, and say so explicitly when the
  # removable fallback the firmware needs is missing.
  grep -q 'ESP contents' "$SCRIPT"
  grep -q 'esp: removable fallback present' "$SCRIPT"
  # Accept either the x86 literal or the arch-parameterised form. The thing
  # this guarantees is that a missing removable fallback is called out BY
  # NAME -- not that the name is always BOOTX64.EFI. On arm64 the firmware
  # looks for BOOTAA64.EFI, so pinning the x86 spelling makes the assertion
  # wrong on exactly the platform #1592 started scheduling ISO cells for,
  # and blocks #1595 from fixing it. Enumerated rather than left open
  # (`EFI/BOOT/` alone) so a typo'd or empty suffix still fails.
  grep -qE 'WARN: esp has NO EFI/BOOT/(BOOTX64\.EFI|\$\{fallback_efi\})' "$SCRIPT"
}

@test "install: the LUKS workflow gives the guest more RAM than the image" {
  # The composefs install path stages the image through podman, so the guest
  # needs headroom over the image, not a hair under it. Keep the LUKS job's
  # --memory above the script default and the recipe's disk pinned to vda so
  # the swap disk can never become the install target.
  local wf="${REPO_ROOT}/.github/workflows/luks-e2e.yml"
  grep -q -- '--memory 10240' "$wf"
  grep -q '"disk": "/dev/vda"' "$SCRIPT"
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
# vsock SSH fallback (tacklebox#178)
# ═══════════════════════════════════════════════════════════════════════════

@test "vsock: transport helpers switch user, home directory and proxy" {
  # Generic (non-tunaOS) images ship no TCP sshd on live media — only
  # systemd-ssh-generator's AF_VSOCK listener. The harness swaps every guest
  # ssh/scp to root-over-vsock through one pair of helper functions; evaluate
  # them out of the script so this fails if the shipped shapes drift.
  run bash -c '
    set -euo pipefail
    src="'"$SCRIPT"'"
    E2E_SSH_OPTS=(-o StrictHostKeyChecking=no)
    SSH_PORT=2222 VSOCK_CID=3222 VSOCK_SSH_KEY=/tmp/never-read
    eval "$(sed -n "/^use_tcp_transport()/,/^}/p" "$src")"
    eval "$(sed -n "/^use_vsock_transport()/,/^}/p" "$src")"
    use_tcp_transport
    [[ "${GUEST_SSH[*]}" == *"liveuser@127.0.0.1"* ]]
    [[ "${GUEST_SCP[*]}" == *"-P 2222"* ]]
    [[ "$GUEST_HOME" == /home/liveuser ]]
    use_vsock_transport
    [[ "${GUEST_SSH[*]}" == *"VSOCK-CONNECT:3222:22"* ]]
    [[ "${GUEST_SSH[*]}" == *"root@"* ]]
    [[ "${GUEST_SCP[*]}" != *"-P "* ]]
    [[ "$GUEST_HOME" == /root ]]
    [[ "$SSH_TRANSPORT" == vsock ]]
    echo SHAPES_OK
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *SHAPES_OK* ]]
}

@test "vsock: guest CID defaults to SSH_PORT+1000 and honors the env override" {
  # CIDs collide across concurrent runs exactly like TCP ports do; deriving
  # from the already collision-managed SSH_PORT keeps one knob. Evaluated out
  # of the script, like the LIVE_MARKER default above.
  local derived override
  derived=$(unset TBOX_E2E_VSOCK_CID; SSH_PORT=2222; eval "$(grep '^VSOCK_CID=' "$SCRIPT")"; echo "$VSOCK_CID")
  [ "$derived" = "3222" ]
  override=$(TBOX_E2E_VSOCK_CID=77 SSH_PORT=2222 bash -c "$(grep '^VSOCK_CID=' "$SCRIPT"); echo \$VSOCK_CID")
  [ "$override" = "77" ]
}

@test "vsock: root key rides the SMBIOS credential, device on the live boot only" {
  # The whole fallback is contract: the key must reach the guest under BOTH
  # credential names. provision.conf's ssh.authorized_keys.root writes
  # /root/.ssh/authorized_keys — which never lands on bootc images, where
  # /root is a symlink into /var/roothome (aurora attempt 7, run
  # 31115116876: vsock handshake completed, "Permission denied (publickey)").
  # ssh.ephemeral-authorized_keys-all is consumed by the generated
  # sshd-vsock instance itself and is the one that actually authenticates
  # there. Both must stay on the QEMU command line of the LIVE boot (the
  # installed boots are serial-gated and get no vsock device).
  grep -q 'io.systemd.credential.binary:ssh.authorized_keys.root=' "$SCRIPT"
  grep -q 'io.systemd.credential.binary:ssh.ephemeral-authorized_keys-all=' "$SCRIPT"
  grep -q 'vhost-vsock-pci,guest-cid=' "$SCRIPT"
  # Absent host support must leave the command line untouched (VSOCK_ARGS
  # stays empty), so the expansion needs the set -u-safe guard form.
  grep -q '\${VSOCK_ARGS\[@\]+"\${VSOCK_ARGS\[@\]}"}' "$SCRIPT"
}

@test "vsock: check_ssh probes tcp first and reports both failures" {
  # tunaOS images must keep the exact tcp path they always had — the vsock
  # probe only runs after tcp fails. And when both fail, both stderrs are
  # reported: on generic images the tcp reset is expected noise and the vsock
  # line is the actual diagnosis.
  grep -q 'check_ssh_vsock' "$SCRIPT"
  grep -qF 'tcp: ${why} | vsock: ${VSOCK_WHY}' "$SCRIPT"
  # The fallback is gated on the device actually having been attached.
  grep -qF '[[ ${#VSOCK_ARGS[@]} -gt 0 ]] && check_ssh_vsock' "$SCRIPT"
}

# ═══════════════════════════════════════════════════════════════════════════
# Generic (no-fisherman) bootc install path
# ═══════════════════════════════════════════════════════════════════════════

@test "generic: qualify_imgref prefixes bare refs and passes qualified ones through" {
  run bash -c '
    set -euo pipefail
    eval "$(sed -n "/^qualify_imgref()/,/^}/p" "'"$SCRIPT"'")"
    [ "$(qualify_imgref ublue-os/aurora:stable)" = "ghcr.io/ublue-os/aurora:stable" ]
    [ "$(qualify_imgref quay.io/fedora/fedora-bootc:42)" = "quay.io/fedora/fedora-bootc:42" ]
    [ "$(qualify_imgref registry.example.com:5000/x/y:z)" = "registry.example.com:5000/x/y:z" ]
    echo REFS_OK
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *REFS_OK* ]]
}

@test "generic: fisherman absence falls back to bootc only when an image is named" {
  # Guessing a registry ref from an ISO filename is how #1006's 40-minute
  # failures happened; the generic path refuses to guess.
  #
  # Both halves sit in one condition, and it reads the image probe rather than
  # /usr/local/bin/fisherman: FISHERMAN_OVERRIDE now lands on the guest before
  # the verifying check, so a later read would find a fisherman on every image
  # and divert nothing. See test_iso_e2e_fisherman_override.bats.
  grep -qF 'if [[ "$image_has_fisherman" -eq 0 && -n "${TBOX_E2E_IMAGE:-}" ]]; then' "$SCRIPT"
  grep -q 'run_install_generic' "$SCRIPT"
  grep -q 'TBOX_E2E_IMAGE is unset' "$SCRIPT"
}

@test "generic: container storage lands on the scratch disk, not the tmpfs root" {
  # The live overlay upperdir is an 8G tmpfs; a stock image pull (aurora ≈
  # 9G uncompressed) cannot land there (#941, from the other direction).
  # The scratch disk is by-serial like the swap disk, attached to the live
  # boot only, and formatted/mounted only by the generic path.
  grep -q 'SCRATCH_DISK="${OUTPUT_DIR}/scratch-disk.qcow2"' "$SCRIPT"
  grep -q 'SCRATCH_DISK_BYID="/dev/disk/by-id/virtio-${SCRATCH_DISK_SERIAL}"' "$SCRIPT"
  [ "$(grep -c 'drive=scratchdisk' "$SCRIPT")" -eq 1 ]
  grep -q 'mkfs.ext4 -q -L tbxscratch ${SCRATCH_DISK_BYID}' "$SCRIPT"
  grep -q 'mount ${SCRATCH_DISK_BYID} /var/lib/containers' "$SCRIPT"
}

@test "fisherman fallback transfers the image onto the scratch disk" {
  # /home/liveuser is the live overlay upperdir and therefore RAM-backed. The
  # fallback must stage the tar under the disk already mounted at
  # /var/lib/containers, or a multi-GB image will exhaust the guest tmpfs.
  grep -q 'guest_tar_dir="/var/lib/containers/tunaos-e2e-transfer"' "$SCRIPT"
  grep -q 'sudo install -d -o liveuser -g liveuser ${guest_tar_dir}' "$SCRIPT"
  grep -q '"${GUEST_SCP_DEST}:${guest_tar}"' "$SCRIPT"
  grep -q 'sudo podman load -i ${guest_tar}' "$SCRIPT"
  ! grep -q '"${GUEST_SCP_DEST}:${GUEST_HOME}/"' "$SCRIPT"
}

@test "generic: bootc install bakes serial kargs and tpm2-luks under --luks" {
  grep -q 'bootc install to-disk --wipe' "$SCRIPT"
  grep -qF 'block_setup="--block-setup tpm2-luks"' "$SCRIPT"
  grep -q -- '--karg console=ttyS0,115200n8 --karg rd.plymouth=0 --karg plymouth.enable=0' "$SCRIPT"
  # bootc gates --block-setup tpm2-luks on the image's install config
  # ("Block setup Tpm2Luks is not enabled in installation config", attempt
  # 11 / run 31125136026). The opt-in is install-time policy, delivered as
  # a drop-in bind-mounted into the installing container — never baked
  # into the image. "direct" must stay enabled alongside it.
  grep -qF 'block = [\"direct\", \"tpm2-luks\"]' "$SCRIPT"
  grep -qF '/usr/lib/bootc/install/90-tbox-luks.toml:ro' "$SCRIPT"
}

@test "generic: the unlock gate restarts swtpm on preserved state" {
  # swtpm exits with its QEMU; bootc sealed the LUKS key against that TPM's
  # state, so the reboot gate must restart it WITHOUT wiping the state dir.
  grep -q 'start_swtpm keep' "$SCRIPT"
  grep -qF '[[ "$keep" == "keep" ]] || rm -rf "$TPM_DIR"' "$SCRIPT"
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


@test "non-composefs canonical offline payload uses Fisherman direct mode" {
  grep -q 'Found canonical offline image.*bootcDirect' "$SCRIPT"
  grep -q 'recipe_image=""' "$SCRIPT"
  grep -q 'containers-storage:<targetImgref>' "$SCRIPT"
}

@test "first-boot harness harvests the emergency shell instead of timing out past it" {
  # guppy:xfce (run 31182709691): "Failed to start Switch Root", dracut
  # emergency shell, and an artifact that proved the failure happened while
  # containing nothing about why — rdsosreport.txt lives inside the guest and
  # died with it. The harness must detect the shell and cat the report to the
  # serial it already captures. Pinned on the CODE strings (the send commands
  # and the detection literal), not the rationale comments.
  local harness="${REPO_ROOT}/scripts/luks-first-boot.py"
  grep -qF '"Entering emergency mode" in text' "$harness"
  grep -qF 'cat /run/initramfs/rdsosreport.txt 2>/dev/null' "$harness"
  grep -qF 'journalctl -b --no-pager -n 120' "$harness"
}

# ── TPM2 auto-unlock verification opt-in (tunaOS#680) ──────────────────────
#
# fisherman#48 moved TPM2 enrollment from install time (sealed against the
# wrong PCR 7 — the live ISO's, not the installed system's; tunaOS#679/#680)
# to a first-boot oneshot on the installed system. The LUKS passphrase gate
# above proves the passphrase-encrypted install works; it never reboots a
# second time with no passphrase, so it cannot prove the oneshot actually
# enrolled a working key. These tests pin the opt-in that closes that gap.

@test "TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK is off by default" {
  grep -qF '${TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK:-0}' "$SCRIPT"
}

@test "TPM auto-unlock verification restarts swtpm for the first installed boot" {
  # fisherman's first-boot oneshot needs /dev/tpmrm0 present on THIS boot to
  # enroll against — without it there is nothing for the later verification
  # boot to ever unlock with. Scoped to the LUKS passphrase gate block (the
  # first `start_swtpm keep` call after the fisherman install, ahead of the
  # TPM auto-unlock verification block below it).
  awk '/LUKS passphrase gate ─/,/TPM auto-unlock verification/' "$SCRIPT" |
    grep -q 'start_swtpm keep'
}

@test "the LUKS passphrase gate boot attaches TPM_ARGS" {
  awk '/LUKS passphrase gate: booting installed disk, injecting passphrase/,/-pidfile "\$QEMU_PIDFILE" -daemonize \|\| \{/' "$SCRIPT" |
    grep -qF '${TPM_ARGS}'
}

@test "TPM auto-unlock verification reboots with no passphrase and requires login" {
  awk '/TPM auto-unlock verification: rebooting/,/^\t\tfi$/' "$SCRIPT" > "${BATS_TEST_TMPDIR}/block.txt"
  grep -q 'start_swtpm keep' "${BATS_TEST_TMPDIR}/block.txt"
  grep -qF '${TPM_ARGS}' "${BATS_TEST_TMPDIR}/block.txt"
  grep -q 'login:|Reached target.*(Graphical|Multi-User)' "${BATS_TEST_TMPDIR}/block.txt"
  # And it must NOT inject anything at a passphrase prompt — the whole point
  # is proving the TPM unlocks it unattended.
  ! grep -q 'sendall(passphrase' "${BATS_TEST_TMPDIR}/block.txt"
}

@test "TPM auto-unlock verification distinguishes a still-passphrase-locked disk from a bare timeout" {
  grep -qF 'passphrase for disk root' "$SCRIPT"
  grep -qF 'reason="passphrase-still-required"' "$SCRIPT"
  grep -qF 'reason="timeout"' "$SCRIPT"
}

@test "TPM auto-unlock verification records confirm/fail evidence markers" {
  grep -qF 'TUNAOS_LUKS_E2E_TPM_AUTOUNLOCK_CONFIRMED' "$SCRIPT"
  grep -qF 'TUNAOS_LUKS_E2E_TPM_AUTOUNLOCK_FAILED' "$SCRIPT"
}

@test "TPM auto-unlock verification failure returns a distinct, documented exit code" {
  awk '/TPM auto-unlock verification FAILED/,/return 8/' "$SCRIPT" | grep -q 'return 8'
  grep -qF '#   8  TPM auto-unlock verification failed' "$SCRIPT"
}

@test "TPM auto-unlock verification preserves its own serial log rather than clobbering others" {
  grep -qF 'installed-tpm-autounlock-serial.log' "$SCRIPT"
}
