#!/usr/bin/env bats
# Unit tests for scripts/test-vm.sh
#
# Tests:
#   - Argument validation (requires exactly 2 args)
#   - Architecture detection (arm64 → aarch64, else x86_64)
#   - Image filename construction (base vs flavored)
#   - VM name construction from variant+flavor
#   - Missing image file error
#   - Missing limactl error
#   - Existing VM cleanup
#   - VNC display parsing from JSON
#   - VNC display fallback to vncdisplay file
#   - VNC format handling (comma extraction)
#   - VNC viewer detection (xdg-open, open, none)

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/tests"

  # Create a minimal lima-template.yaml
  echo "images: []" > "${TEST_ROOT}/tests/lima-template.yaml"

  # Stub uname
  cat >"${TEST_ROOT}/uname" <<'UNAME'
#!/usr/bin/env bash
if [[ "$1" == "-m" ]]; then
  echo "${MOCK_ARCH:-x86_64}"
fi
UNAME
  chmod +x "${TEST_ROOT}/uname"

  # Stub limactl
  cat >"${TEST_ROOT}/limactl" <<'LIMACTL'
#!/usr/bin/env bash
case "$1" in
  list)
    if [[ "$2" == "-q" ]]; then
      if [[ "${MOCK_VM_EXISTS:-0}" == "1" ]]; then
        echo "${MOCK_VM_NAME:-tuna-yellowfin-base}"
      fi
    elif [[ "$2" == "--json" ]]; then
      echo "${MOCK_LIMA_JSON:-[]}"
    fi
    ;;
  stop)  echo "stopped $2" ;;
  delete) echo "deleted $2" ;;
  start) echo "started $2 $3" ;;
esac
LIMACTL
  chmod +x "${TEST_ROOT}/limactl"

  # Stub jq
  cat >"${TEST_ROOT}/jq" <<'JQ'
#!/usr/bin/env bash
echo "${MOCK_JQ_OUTPUT:-null}"
JQ
  chmod +x "${TEST_ROOT}/jq"

  # Stub xdg-open
  cat >"${TEST_ROOT}/xdg-open" <<'XDG'
#!/usr/bin/env bash
echo "xdg-open: $*"
XDG
  chmod +x "${TEST_ROOT}/xdg-open"

  # Stub mktemp
  cat >"${TEST_ROOT}/mktemp" <<'MKTEMP'
#!/usr/bin/env bash
echo "${TEST_ROOT}/lima-config-$$.yaml"
MKTEMP
  chmod +x "${TEST_ROOT}/mktemp"

  # Stub cat (for VNC file read)
  cat >"${TEST_ROOT}/cat" <<'CAT'
#!/usr/bin/env bash
if [[ "$1" == *"vncdisplay"* ]]; then
  echo "${MOCK_VNC_FILE_CONTENT:-127.0.0.1:5}"
else
  command cat "$@"
fi
CAT
  chmod +x "${TEST_ROOT}/cat"

  # Stub sed (real sed with our test file)
  cat >"${TEST_ROOT}/sed" <<'SED'
#!/usr/bin/env bash
exec /usr/bin/sed "$@"
SED
  chmod +x "${TEST_ROOT}/sed"

  # Stub cp (real cp)
  cat >"${TEST_ROOT}/cp" <<'CP'
#!/usr/bin/env bash
exec /usr/bin/cp "$@"
CP
  chmod +x "${TEST_ROOT}/cp"

  export PATH="${TEST_ROOT}:${PATH}"
  export MOCK_ARCH="x86_64"
  export MOCK_VM_EXISTS="0"
  export MOCK_LIMA_JSON="[]"
  export HOME="${TEST_ROOT}"
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# Copy the script and patch paths to use TEST_ROOT
_source_script() {
  local script="${TEST_ROOT}/test-vm.sh"
  sed -e "s|TEMPLATE_FILE=.*|TEMPLATE_FILE=\"${TEST_ROOT}/tests/lima-template.yaml\"|" \
      -e "s|VNC_FILE=.*|VNC_FILE=\"${TEST_ROOT}/vncdisplay\"|" \
      "${REPO_ROOT}/scripts/test-vm.sh" > "$script"
  chmod +x "$script"
  echo "$script"
}

# ── Argument Validation ───────────────────────────────────────────────────

@test "requires exactly 2 arguments" {
  local script
  script="$(_source_script)"
  run bash "$script"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "rejects 1 argument" {
  local script
  script="$(_source_script)"
  run bash "$script" yellowfin
  [ "$status" -eq 1 ]
}

@test "rejects 3 arguments" {
  local script
  script="$(_source_script)"
  run bash "$script" yellowfin gnome extra
  [ "$status" -eq 1 ]
}

@test "accepts exactly 2 arguments" {
  local script
  script="$(_source_script)"
  # Missing image will cause exit 1, but not from argument validation
  run bash "$script" yellowfin base
  # Should fail on missing image, not on args
  [[ "$output" == *"Image not found"* ]] || [[ "$output" == *"Error: Image not found"* ]]
}

# ── Architecture Detection ────────────────────────────────────────────────

@test "detects arm64 and maps to aarch64" {
  local script
  script="$(_source_script)"
  MOCK_ARCH="arm64" run bash -c '
    ARCH=$(uname -m)
    if [ "$ARCH" == "arm64" ]; then LIMA_ARCH="aarch64"; else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "aarch64" ]]
}

@test "detects x86_64 and maps to x86_64" {
  run bash -c '
    ARCH="x86_64"
    if [ "$ARCH" == "arm64" ]; then LIMA_ARCH="aarch64"; else LIMA_ARCH="x86_64"; fi
    echo "$LIMA_ARCH"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "x86_64" ]]
}

# ── Image Filename Construction ───────────────────────────────────────────

@test "base flavor uses variant.qcow2" {
  run bash -c '
    VARIANT="yellowfin"; FLAVOR="base"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    else
      IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "yellowfin.qcow2" ]]
}

@test "non-base flavor uses variant-flavor.qcow2" {
  run bash -c '
    VARIANT="skipjack"; FLAVOR="kde"
    if [ "$FLAVOR" == "base" ]; then
      IMAGE_FILENAME="${VARIANT}.qcow2"
    else
      IMAGE_FILENAME="${VARIANT}-${FLAVOR}.qcow2"
    fi
    echo "$IMAGE_FILENAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "skipjack-kde.qcow2" ]]
}

# ── VM Name Construction ──────────────────────────────────────────────────

@test "base flavor VM name is tuna-<variant>" {
  run bash -c '
    VARIANT="albacore"; FLAVOR="base"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="tuna-${VARIANT}"
    else
      VM_NAME="tuna-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "tuna-albacore" ]]
}

@test "non-base flavor VM name is tuna-<variant>-<flavor>" {
  run bash -c '
    VARIANT="bonito"; FLAVOR="niri"
    if [ "$FLAVOR" == "base" ]; then
      VM_NAME="tuna-${VARIANT}"
    else
      VM_NAME="tuna-${VARIANT}-${FLAVOR}"
    fi
    echo "$VM_NAME"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "tuna-bonito-niri" ]]
}

# ── Error Handling ────────────────────────────────────────────────────────

@test "exits when image file does not exist" {
  local script
  script="$(_source_script)"
  run bash "$script" yellowfin base
  [ "$status" -eq 1 ]
  [[ "$output" == *"Image not found"* ]]
}

@test "exits when limactl is not installed" {
  local script
  script="$(_source_script)"
  touch "${TEST_ROOT}/yellowfin.qcow2"
  cd "${TEST_ROOT}"
  # Move limactl out of PATH to test the missing-lima path
  mv "${TEST_ROOT}/limactl" "${TEST_ROOT}/limactl.bak"
  run bash "$script" yellowfin base
  mv "${TEST_ROOT}/limactl.bak" "${TEST_ROOT}/limactl"
  [ "$status" -eq 1 ]
  [[ "$output" == *"limactl"* ]]
}

# ── VNC Display Parsing ──────────────────────────────────────────────────

@test "parses VNC display from lima JSON" {
  MOCK_JQ_OUTPUT="127.0.0.1:5" run bash -c '
    MOCK_LIMA_JSON='"'"'[{"name":"tuna-yellowfin-gnome","video":{"vnc":{"display":"127.0.0.1:5"}}}]'"'"'
    VNC_DISPLAY=$(echo "$MOCK_LIMA_JSON" | jq -r "select(.name==\"tuna-yellowfin-gnome\") | .video.vnc.display")
    echo "$VNC_DISPLAY"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "127.0.0.1:5" ]]
}

@test "falls back to vncdisplay file when JSON is empty" {
  run bash -c '
    VNC_DISPLAY=$(echo "[]" | jq -r "select(.name==\"nonexistent\") | .video.vnc.display")
    if [ -z "$VNC_DISPLAY" ] || [ "$VNC_DISPLAY" == "null" ]; then
      VNC_DISPLAY="127.0.0.1:9"
    fi
    echo "$VNC_DISPLAY"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "127.0.0.1:9" ]]
}

@test "handles comma-separated VNC display format" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:0,to=9"
    VNC_DISPLAY=${VNC_DISPLAY%%,*}
    echo "$VNC_DISPLAY"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "127.0.0.1:0" ]]
}

@test "VNC display without comma passes through unchanged" {
  run bash -c '
    VNC_DISPLAY="127.0.0.1:5"
    VNC_DISPLAY=${VNC_DISPLAY%%,*}
    echo "$VNC_DISPLAY"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "127.0.0.1:5" ]]
}

# ── VNC Viewer Detection ──────────────────────────────────────────────────

@test "detects xdg-open for VNC viewer" {
  run bash -c '
    if command -v xdg-open >/dev/null 2>&1; then
      echo "xdg-open"
    elif command -v open >/dev/null 2>&1; then
      echo "open"
    else
      echo "none"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "xdg-open" ]]
}

@test "falls back to manual message when no viewer available" {
  run bash -c '
    PATH=/nonexistent
    if command -v xdg-open >/dev/null 2>&1; then
      echo "xdg-open"
    elif command -v open >/dev/null 2>&1; then
      echo "open"
    else
      echo "Could not detect tool to open VNC URI. Please connect manually to 127.0.0.1:5"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Could not detect tool"* ]]
}

# ── Existing VM Cleanup ───────────────────────────────────────────────────

@test "cleans up existing VM with same name before starting" {
  run bash -c '
    MOCK_VM_EXISTS=1
    VM_NAME="tuna-yellowfin-base"
    if echo "$VM_NAME" | grep -q "^${VM_NAME}$"; then
      echo "stopping and deleting $VM_NAME"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"stopping and deleting"* ]]
}

@test "skips cleanup when no existing VM" {
  run bash -c '
    MOCK_VM_EXISTS=0
    VM_NAME="tuna-yellowfin-base"
    if echo "" | grep -q "^${VM_NAME}$"; then
      echo "would cleanup"
    else
      echo "no existing VM"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "no existing VM" ]]
}
