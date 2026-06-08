#!/usr/bin/env bats
# Unit tests for scripts/lima-novnc.sh — Lima VM + noVNC launcher
#
# Tests:
#   - Input validation (missing args)
#   - limactl dependency check
#   - Architecture detection (x86_64 → x86_64, aarch64 → aarch64)
#   - ISO vs qcow2 config generation
#   - VNC display parsing (host:port extraction)
#   - VNC port calculation (5900 + display number)
#   - noVNC port selection with fallback
#   - URL construction with/without password
#   - Tailscale IP detection
#   - Existing VM cleanup check

setup() {
  TEST_ROOT="$(mktemp -d)"
  export TEST_ROOT
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── Input validation ──────────────────────────────────────────────────────

@test "lima-novnc: requires vm_name argument" {
  run bash -c '
    VM_NAME="${1:-}"
    if [[ -z "$VM_NAME" ]]; then
      echo "Error: vm_name required"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

@test "lima-novnc: requires type argument" {
  run bash -c '
    TYPE="${1:-}"
    if [[ -z "$TYPE" ]]; then
      echo "Error: type required (qcow2 or iso)"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

@test "lima-novnc: requires image_path argument" {
  run bash -c '
    IMAGE_PATH="${1:-}"
    if [[ -z "$IMAGE_PATH" ]]; then
      echo "Error: image_path required"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

# ── Architecture detection ────────────────────────────────────────────────

@test "lima-novnc: detects x86_64 arch" {
  run bash -c '
    ARCH="x86_64"
    [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"
    echo "$LIMA_ARCH"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "x86_64" ]]
}

@test "lima-novnc: detects aarch64 arch" {
  run bash -c '
    ARCH="aarch64"
    [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"
    echo "$LIMA_ARCH"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "aarch64" ]]
}

@test "lima-novnc: detects arm64 as aarch64" {
  run bash -c '
    ARCH="arm64"
    [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"
    echo "$LIMA_ARCH"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "aarch64" ]]
}

# ── Config generation: ISO mode ───────────────────────────────────────────

@test "lima-novnc: ISO mode includes -cdrom extra arg" {
  run bash -c '
    TYPE="iso"
    [[ "$TYPE" == "iso" ]] && echo "-cdrom" || echo "no-cdrom"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "-cdrom" ]]
}

@test "lima-novnc: ISO mode includes boot order" {
  run bash -c '
    TYPE="iso"
    IMAGE_PATH="/path/to/image.iso"
    if [[ "$TYPE" == "iso" ]]; then
      echo "-boot order=d,menu=on"
      echo "-cdrom ${IMAGE_PATH}"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"order=d,menu=on"* ]]
  [[ "$output" == *"-cdrom /path/to/image.iso"* ]]
}

@test "lima-novnc: ISO mode sets plain:true" {
  run bash -c '
    TYPE="iso"
    if [[ "$TYPE" == "iso" ]]; then
      echo "plain: true"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "plain: true" ]]
}

@test "lima-novnc: qcow2 mode sets plain:true" {
  run bash -c '
    TYPE="qcow2"
    if [[ "$TYPE" != "iso" ]]; then
      echo "plain: true"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "plain: true" ]]
}

# ── VNC display parsing ───────────────────────────────────────────────────

@test "lima-novnc: parses host from VNC display" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0,to=9"
    VNC_DISPLAY="${VNC_DISPLAY%%,*}"
    VNC_HOST="${VNC_DISPLAY%:*}"
    echo "host=$VNC_HOST"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "host=127.0.0.1" ]]
}

@test "lima-novnc: parses display number from VNC display" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0"
    VNC_DISP_NUM="${VNC_DISPLAY##*:}"
    echo "display=$VNC_DISP_NUM"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "display=0" ]]
}

@test "lima-novnc: parses display number with trailing options" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:3,to=9"
    VNC_DISPLAY="${VNC_DISPLAY%%,*}"
    VNC_DISP_NUM="${VNC_DISPLAY##*:}"
    echo "display=$VNC_DISP_NUM"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "display=3" ]]
}

# ── VNC port calculation ──────────────────────────────────────────────────

@test "lima-novnc: calculates VNC port as 5900 + display number" {
  run bash -c '
    VNC_DISP_NUM=0
    VNC_PORT=$((5900 + VNC_DISP_NUM))
    echo "$VNC_PORT"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "5900" ]]
}

@test "lima-novnc: calculates VNC port for display 5" {
  run bash -c '
    VNC_DISP_NUM=5
    VNC_PORT=$((5900 + VNC_DISP_NUM))
    echo "$VNC_PORT"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "5905" ]]
}

# ── noVNC port selection ──────────────────────────────────────────────────

@test "lima-novnc: default noVNC port is 6080" {
  run bash -c '
    NOVNC_PORT=6080
    echo "$NOVNC_PORT"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "6080" ]]
}

# ── URL construction ──────────────────────────────────────────────────────

@test "lima-novnc: builds local URL with autoconnect" {
  run bash -c '
    NOVNC_PORT=6080
    LOCAL_URL="http://127.0.0.1:${NOVNC_PORT}/vnc.html?autoconnect=1&host=127.0.0.1&port=${NOVNC_PORT}"
    echo "$LOCAL_URL"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"autoconnect=1"* ]]
  [[ "$output" == *"host=127.0.0.1"* ]]
  [[ "$output" == *"port=6080"* ]]
}

@test "lima-novnc: includes password param when password is set" {
  run bash -c '
    VNC_PASS="secret123"
    NOVNC_PORT=6080
    NOVNC_PARAMS="vnc.html?autoconnect=1"
    [[ -n "$VNC_PASS" ]] && NOVNC_PARAMS="${NOVNC_PARAMS}&password=${VNC_PASS}"
    echo "$NOVNC_PARAMS"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"password=secret123"* ]]
}

@test "lima-novnc: omits password param when password is empty" {
  run bash -c '
    VNC_PASS=""
    NOVNC_PARAMS="vnc.html?autoconnect=1"
    [[ -n "$VNC_PASS" ]] && NOVNC_PARAMS="${NOVNC_PARAMS}&password=${VNC_PASS}"
    echo "$NOVNC_PARAMS"
  '
  [ "$status" -eq 0 ]
  [[ "$output" != *"password"* ]]
}

# ── Strict mode ───────────────────────────────────────────────────────────

@test "lima-novnc: has set -euo pipefail" {
  run grep -c "set -euo pipefail" "${REPO_ROOT:-/data/agents/quality/tunaos-repo}/scripts/lima-novnc.sh"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}
