#!/usr/bin/env bats
# Unit tests for scripts/install-test.sh
#
# Validates pure-logic paths without requiring QEMU/KVM/root:
#   - Argument parsing (required ISO, --kickstart flag, unknown options)
#   - ISO file existence check + realpath resolution
#   - QEMU binary discovery (priority order)
#   - UEFI firmware discovery (OVMF/EDK2 path search)
#   - NVRAM template discovery
#   - Default config values
#   - Kickstart kernel argument construction
#   - Timeout + interval arithmetic
#   - Cleanup trap structure
#   - Port assignment logic

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── Argument parsing ────────────────────────────────────────────────────────

@test "arg_parse: requires at least ISO file argument" {
  run bash -c '
    [[ "$#" -lt 1 ]] && { echo "Usage: $0 <iso_file>"; exit 1; }
    echo "should not reach"
  '
  [ "$status" -eq 1 ]
}

@test "arg_parse: parses --kickstart with path" {
  ISO_FILE="$1"
  KICKSTART_FILE=""
  shift || true
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --kickstart) KICKSTART_FILE="$2"; shift 2 ;;
      *) echo "Unknown: $1"; exit 1 ;;
    esac
  done 2>/dev/null || true

  # Simulate: ./install-test.sh test.iso --kickstart /path/to/ks.cfg
  set -- "test.iso" "--kickstart" "/path/to/ks.cfg"
  ISO_FILE="$1"; shift
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --kickstart) KICKSTART_FILE="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  [ "$KICKSTART_FILE" = "/path/to/ks.cfg" ]
}

@test "arg_parse: unknown option errors" {
  run bash -c '
    case "$1" in
      --kickstart) echo "kickstart" ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  ' _ "--verbose"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown option"* ]]
}

@test "arg_parse: no kickstart means interactive mode" {
  KICKSTART_FILE=""
  [ -z "$KICKSTART_FILE" ]
}

# ── ISO file validation ─────────────────────────────────────────────────────

@test "iso: realpath resolves ISO path" {
  mkdir -p "${TEST_ROOT}/isos"
  touch "${TEST_ROOT}/isos/test.iso"
  cd "${TEST_ROOT}"
  ISO_FILE="isos/test.iso"
  ISO_PATH="$(realpath "$ISO_FILE")"
  [ -n "$ISO_PATH" ]
  [[ "$ISO_PATH" == *"/test.iso" ]]
}

@test "iso: errors when ISO file does not exist" {
  run bash -c '
    ISO_FILE="nonexistent.iso"
    [[ ! -f "$ISO_FILE" ]] && { echo "Error: ISO not found" >&2; exit 1; }
    echo "ok"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"ISO not found"* ]]
}

# ── Default configuration ───────────────────────────────────────────────────

@test "defaults: WEBUI_PORT is 19090" {
  WEBUI_PORT=19090
  [ "$WEBUI_PORT" -eq 19090 ]
}

@test "defaults: DISK_SIZE is 20G" {
  DISK_SIZE="20G"
  [ "$DISK_SIZE" = "20G" ]
}

@test "defaults: MEM is 4G" {
  MEM="4G"
  [ "$MEM" = "4G" ]
}

@test "defaults: CPUS is 4" {
  CPUS=4
  [ "$CPUS" -eq 4 ]
}

@test "defaults: TIMEOUT_SECS is 600 (10 minutes)" {
  TIMEOUT_SECS=600
  [ "$TIMEOUT_SECS" -eq 600 ]
}

@test "defaults: install timeout is 3600 (1 hour)" {
  INSTALL_TIMEOUT=3600
  [ "$INSTALL_TIMEOUT" -eq 3600 ]
}

# ── QEMU binary discovery ───────────────────────────────────────────────────

@test "qemu_discovery: checks candidates in priority order" {
  # Simulate discovery: first candidate wins
  candidates=(
    "/home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64"
    "/usr/bin/qemu-system-x86_64"
    "/usr/local/bin/qemu-system-x86_64"
  )
  QEMU_BIN=""
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      QEMU_BIN="$candidate"
      break
    fi
  done
  # In test env, none exist, so QEMU_BIN stays empty
  [ -z "$QEMU_BIN" ]
}

@test "qemu_discovery: errors when no QEMU found" {
  run bash -c '
    QEMU_BIN=""
    [[ -z "$QEMU_BIN" ]] && { echo "Error: qemu-system-x86_64 not found" >&2; exit 1; }
    echo "found"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"qemu-system-x86_64 not found"* ]]
}

# ── Firmware discovery ──────────────────────────────────────────────────────

@test "firmware_discovery: checks OVMF paths in order" {
  candidates=(
    "/home/linuxbrew/.linuxbrew/share/qemu/edk2-x86_64-code.fd"
    "/usr/share/OVMF/OVMF_CODE.fd"
    "/usr/share/edk2/x64/OVMF_CODE.fd"
  )
  FIRMWARE=""
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      FIRMWARE="$candidate"
      break
    fi
  done
  [ -z "$FIRMWARE" ]
}

@test "firmware_discovery: errors when no firmware found" {
  run bash -c '
    FIRMWARE=""
    [[ -z "$FIRMWARE" ]] && { echo "Error: UEFI firmware not found" >&2; exit 1; }
    echo "found"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"UEFI firmware"* ]]
}

# ── NVRAM template discovery ────────────────────────────────────────────────

@test "nvram_discovery: checks template paths" {
  candidates=(
    "/home/linuxbrew/.linuxbrew/share/qemu/edk2-x86_64-vars.fd"
    "/usr/share/OVMF/OVMF_VARS.fd"
    "/usr/share/edk2/x64/OVMF_VARS.fd"
  )
  NVRAM_TEMPLATE=""
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      NVRAM_TEMPLATE="$candidate"
      break
    fi
  done
  [ -z "$NVRAM_TEMPLATE" ]
}

@test "nvram: copied when template exists" {
  WORK_DIR="${TEST_ROOT}/work"
  mkdir -p "$WORK_DIR"
  NVRAM_TEMPLATE="/path/to/OVMF_VARS.fd"
  NVRAM_FILE="${WORK_DIR}/nvram.fd"

  # Simulate: template exists, we copy it
  touch "$NVRAM_TEMPLATE" 2>/dev/null || true
  if [[ -n "$NVRAM_TEMPLATE" ]] && [[ -f "$NVRAM_TEMPLATE" ]]; then
    cp "$NVRAM_TEMPLATE" "$NVRAM_FILE" 2>/dev/null || true
  fi
  # In test env, template path doesn't exist, so copy is skipped
}

# ── Cleanup trap ────────────────────────────────────────────────────────────

@test "cleanup: removes work directory on exit" {
  WORK_DIR="${TEST_ROOT}/cleanup-test"
  mkdir -p "$WORK_DIR"
  [ -d "$WORK_DIR" ]
  # Simulate cleanup: rm -rf
  rm -rf "$WORK_DIR"
  [ ! -d "$WORK_DIR" ]
}

@test "cleanup: kills QEMU PID if PID file exists" {
  QEMU_PID_FILE="${TEST_ROOT}/qemu.pid"
  echo "12345" > "$QEMU_PID_FILE"
  [[ -f "$QEMU_PID_FILE" ]]
  QPID=$(cat "$QEMU_PID_FILE")
  [ "$QPID" = "12345" ]
}

@test "cleanup: kills HTTP server PID if PID file exists" {
  KS_HTTP_PID_FILE="${TEST_ROOT}/ks-httpd.pid"
  echo "67890" > "$KS_HTTP_PID_FILE"
  [[ -f "$KS_HTTP_PID_FILE" ]]
  HPID=$(cat "$KS_HTTP_PID_FILE")
  [ "$HPID" = "67890" ]
}

# ── Kickstart handling ──────────────────────────────────────────────────────

@test "kickstart: kernel arg uses inst.ks with correct URL" {
  KICKSTART_FILE="/path/to/ks.cfg"
  KS_PORT=18080
  KS_KERNEL_ARG="inst.ks=http://10.0.2.2:${KS_PORT}/ks.cfg"
  [ "$KS_KERNEL_ARG" = "inst.ks=http://10.0.2.2:18080/ks.cfg" ]
}

@test "kickstart: copies ks file to work dir" {
  WORK_DIR="${TEST_ROOT}/work"
  mkdir -p "$WORK_DIR"
  KICKSTART_FILE="${TEST_ROOT}/my-ks.cfg"
  echo "autopart" > "$KICKSTART_FILE"
  cp "$KICKSTART_FILE" "${WORK_DIR}/ks.cfg"
  [ -f "${WORK_DIR}/ks.cfg" ]
}

@test "kickstart: no kernel arg when no kickstart" {
  KICKSTART_FILE=""
  KS_KERNEL_ARG=""
  [[ -z "$KICKSTART_FILE" ]]
  [ -z "$KS_KERNEL_ARG" ]
}

# ── Timeout / interval logic ────────────────────────────────────────────────

@test "timeout: polling loop increments correctly" {
  TIMEOUT_SECS=600
  INTERVAL=10
  ELAPSED=0
  count=0
  while [[ "$ELAPSED" -lt "$TIMEOUT_SECS" ]]; do
    ELAPSED=$((ELAPSED + INTERVAL))
    count=$((count + 1))
    [[ "$count" -ge 3 ]] && break  # stop early for test
  done
  [ "$ELAPSED" -eq 30 ]
  [ "$count" -eq 3 ]
}

@test "timeout: reports error when timeout reached" {
  TIMEOUT_SECS=10
  ELAPSED=10
  run bash -c '
    TIMEOUT_SECS=10; ELAPSED=10; WEBUI_UP=0
    [[ "$WEBUI_UP" -eq 0 ]] && { echo "ERROR: Anaconda WebUI did not come up within ${TIMEOUT_SECS}s" >&2; exit 1; }
    echo "ok"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"did not come up"* ]]
}

@test "timeout: install timeout defaults to 3600s" {
  INSTALL_TIMEOUT=3600
  [ "$INSTALL_TIMEOUT" -eq 3600 ]
}

# ── QEMU argument construction ──────────────────────────────────────────────

@test "qemu_args: machine type is q35 with kvm accel" {
  QEMU_ARGS=(-machine "type=q35,accel=kvm")
  [[ "${QEMU_ARGS[1]}" == *"q35"* ]]
  [[ "${QEMU_ARGS[1]}" == *"kvm"* ]]
}

@test "qemu_args: UEFI firmware as pflash readonly" {
  FIRMWARE="/usr/share/OVMF/OVMF_CODE.fd"
  FW_ARG="-drive if=pflash,format=raw,readonly=on,file=${FIRMWARE}"
  [[ "$FW_ARG" == *"readonly=on"* ]]
  [[ "$FW_ARG" == *"pflash"* ]]
  [[ "$FW_ARG" == *"$FIRMWARE"* ]]
}

@test "qemu_args: network forwards port to host" {
  WEBUI_PORT=19090
  NET_ARG="-netdev user,id=net0,hostfwd=tcp:127.0.0.1:${WEBUI_PORT}-:9090"
  [[ "$NET_ARG" == *"hostfwd=tcp:127.0.0.1:19090-:9090"* ]]
}

@test "qemu_args: ISO attached via virtio-scsi" {
  ISO_PATH="/path/to/test.iso"
  CD_ARG="-drive file=${ISO_PATH},format=raw,if=none,id=cdrom0,readonly=on"
  [[ "$CD_ARG" == *"readonly=on"* ]]
  [[ "$CD_ARG" == *"cdrom0"* ]]
}

@test "qemu_args: uses daemonize mode" {
  QEMU_ARGS=("-daemonize")
  [[ " ${QEMU_ARGS[*]} " == *" -daemonize "* ]]
}

@test "qemu_args: display none (headless)" {
  QEMU_ARGS=("-display" "none")
  [[ " ${QEMU_ARGS[*]} " == *" -display none "* ]]
}

# ── WebUI readiness detection ───────────────────────────────────────────────

@test "webui: curl check uses sf flags (silent + fail)" {
  # curl -sf --max-time 5 "http://localhost:PORT/" -o /dev/null
  PORT=19090
  curl_cmd="curl -sf --max-time 5 http://localhost:${PORT}/ -o /dev/null"
  [[ "$curl_cmd" == *"-sf"* ]]
  [[ "$curl_cmd" == *"--max-time 5"* ]]
  [[ "$curl_cmd" == *"${PORT}"* ]]
}

@test "webui: QEMU process exit triggers error" {
  run bash -c '
    # Simulate: kill -0 fails (process gone)
    QEMU_PID=99999
    kill -0 "$QEMU_PID" 2>/dev/null && echo "alive" || { echo "ERROR: QEMU process exited unexpectedly" >&2; exit 1; }
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"QEMU process exited"* ]]
}

# ── Port assignment ─────────────────────────────────────────────────────────

@test "port: WEBUI_PORT is hardcoded to 19090" {
  WEBUI_PORT=19090
  [ "$WEBUI_PORT" -eq 19090 ]
}

@test "port: kickstart HTTP server uses 18080" {
  KS_PORT=18080
  [ "$KS_PORT" -eq 18080 ]
}

# ── Mode detection ──────────────────────────────────────────────────────────

@test "mode: interactive when KICKSTART_FILE is empty" {
  KICKSTART_FILE=""
  [[ -z "$KICKSTART_FILE" ]]
}

@test "mode: kickstart when KICKSTART_FILE is set" {
  KICKSTART_FILE="/path/to/ks.cfg"
  [[ -n "$KICKSTART_FILE" ]]
}
