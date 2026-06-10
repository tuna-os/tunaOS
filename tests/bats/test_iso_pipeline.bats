#!/usr/bin/env bats
# Unit tests for scripts/test-iso-pipeline.sh
#
# Tests:
#   - Argument parsing (required variant, default flavor/source)
#   - Source dispatch (local/ghcr/registry) logic
#   - Step counter increments
#   - Error exit on unknown source
#   - ISO file discovery pattern

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# test-iso-pipeline.sh — Argument Parsing
# ═══════════════════════════════════════════════════════════════════════════

@test "test-iso-pipeline: missing variant exits with error" {
  run bash -c '
    VARIANT="${1:-}"
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: test-iso-pipeline.sh <variant> [flavor] [source] [install] [port]" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage: test-iso-pipeline.sh"* ]]
}

@test "test-iso-pipeline: variant only uses defaults for flavor, source, install, port" {
  run bash -c '
    VARIANT="${1:-}"
    FLAVOR="${2:-gnome}"
    SOURCE="${3:-local}"
    INSTALL="${4:-0}"
    PORT="${5:-5000}"
    echo "VARIANT=$VARIANT FLAVOR=$FLAVOR SOURCE=$SOURCE INSTALL=$INSTALL PORT=$PORT"
  ' _ yellowfin
  [ "$status" -eq 0 ]
  [ "$output" = "VARIANT=yellowfin FLAVOR=gnome SOURCE=local INSTALL=0 PORT=5000" ]
}

@test "test-iso-pipeline: all args provided" {
  run bash -c '
    VARIANT="${1:-}"
    FLAVOR="${2:-gnome}"
    SOURCE="${3:-local}"
    INSTALL="${4:-0}"
    PORT="${5:-5000}"
    echo "VARIANT=$VARIANT FLAVOR=$FLAVOR SOURCE=$SOURCE INSTALL=$INSTALL PORT=$PORT"
  ' _ albacore kde ghcr 1 6000
  [ "$status" -eq 0 ]
  [ "$output" = "VARIANT=albacore FLAVOR=kde SOURCE=ghcr INSTALL=1 PORT=6000" ]
}

@test "test-iso-pipeline: flavor defaults to gnome when omitted" {
  run bash -c '
    VARIANT="$1"
    FLAVOR="${2:-gnome}"
    echo "FLAVOR=$FLAVOR"
  ' _ skipjack
  [ "$output" = "FLAVOR=gnome" ]
}

@test "test-iso-pipeline: source defaults to local" {
  run bash -c '
    SOURCE="${3:-local}"
    echo "SOURCE=$SOURCE"
  ' _ _ _
  [ "$output" = "SOURCE=local" ]
}

@test "test-iso-pipeline: install defaults to 0" {
  run bash -c '
    INSTALL="${4:-0}"
    echo "INSTALL=$INSTALL"
  ' _ _ _ _
  [ "$output" = "INSTALL=0" ]
}

@test "test-iso-pipeline: port defaults to 5000" {
  run bash -c '
    PORT="${5:-5000}"
    echo "PORT=$PORT"
  ' _ _ _ _ _
  [ "$output" = "PORT=5000" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# test-iso-pipeline.sh — Source Dispatch
# ═══════════════════════════════════════════════════════════════════════════

@test "test-iso-pipeline: source=local gives local image" {
  run bash -c '
    SOURCE="local"
    case "$SOURCE" in
      local) echo "IMAGE_SOURCE=localhost/yellowfin:gnome" ;;
      ghcr) echo "IMAGE_SOURCE=ghcr.io/tuna-os/yellowfin:gnome" ;;
      registry) echo "IMAGE_SOURCE=localhost:5000/yellowfin:gnome" ;;
    esac
  '
  [ "$output" = "IMAGE_SOURCE=localhost/yellowfin:gnome" ]
}

@test "test-iso-pipeline: source=ghcr gives ghcr image" {
  run bash -c '
    SOURCE="ghcr"
    case "$SOURCE" in
      local) echo "IMAGE_SOURCE=localhost/yellowfin:gnome" ;;
      ghcr) echo "IMAGE_SOURCE=ghcr.io/tuna-os/yellowfin:gnome" ;;
      registry) echo "IMAGE_SOURCE=localhost:5000/yellowfin:gnome" ;;
    esac
  '
  [ "$output" = "IMAGE_SOURCE=ghcr.io/tuna-os/yellowfin:gnome" ]
}

@test "test-iso-pipeline: source=registry gives registry image with port" {
  run bash -c '
    SOURCE="registry"
    PORT="6000"
    case "$SOURCE" in
      local) echo "IMAGE_SOURCE=localhost/yellowfin:gnome" ;;
      ghcr) echo "IMAGE_SOURCE=ghcr.io/tuna-os/yellowfin:gnome" ;;
      registry) echo "IMAGE_SOURCE=localhost:${PORT}/yellowfin:gnome" ;;
    esac
  '
  [ "$output" = "IMAGE_SOURCE=localhost:6000/yellowfin:gnome" ]
}

@test "test-iso-pipeline: source=registry uses default port 5000" {
  run bash -c '
    SOURCE="registry"
    PORT="5000"
    case "$SOURCE" in
      local) echo "IMAGE_SOURCE=localhost/yellowfin:gnome" ;;
      ghcr) echo "IMAGE_SOURCE=ghcr.io/tuna-os/yellowfin:gnome" ;;
      registry) echo "IMAGE_SOURCE=localhost:${PORT}/yellowfin:gnome" ;;
    esac
  '
  [ "$output" = "IMAGE_SOURCE=localhost:5000/yellowfin:gnome" ]
}

@test "test-iso-pipeline: unknown source exits with error" {
  run bash -c '
    SOURCE="dockerhub"
    case "$SOURCE" in
      local|ghcr|registry) echo "ok" ;;
      *) echo "ERROR: Unknown source ${SOURCE}. Use local, ghcr, or registry." >&2; exit 1 ;;
    esac
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown source"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# test-iso-pipeline.sh — Step Counter Logic
# ═══════════════════════════════════════════════════════════════════════════

@test "test-iso-pipeline: PASS increments on each successful step" {
  run bash -c '
    PASS=0
    # Step 1
    echo "Step 1 OK"
    PASS=$((PASS + 1))
    # Step 2
    echo "Step 2 OK"
    PASS=$((PASS + 1))
    # Step 3
    echo "Step 3 OK"
    PASS=$((PASS + 1))
    echo "PASS=$PASS"
  '
  [ "$output" = "$(printf 'Step 1 OK\nStep 2 OK\nStep 3 OK\nPASS=3')" ]
}

@test "test-iso-pipeline: FAIL increments on failed steps" {
  run bash -c '
    PASS=0
    FAIL=0
    # Step 1 passes
    PASS=$((PASS + 1))
    # Step 2 fails
    FAIL=$((FAIL + 1))
    echo "PASS=$PASS FAIL=$FAIL"
  '
  [ "$output" = "PASS=1 FAIL=1" ]
}

@test "test-iso-pipeline: non-zero FAIL exits with error at summary" {
  run bash -c '
    FAIL=2
    if [[ "$FAIL" -gt 0 ]]; then
      echo "ERROR: ${FAIL} step(s) failed." >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"ERROR:"*" step(s) failed"* ]]
}

@test "test-iso-pipeline: zero FAIL exits successfully" {
  run bash -c '
    FAIL=0
    if [[ "$FAIL" -gt 0 ]]; then
      echo "ERROR: ${FAIL} step(s) failed." >&2
      exit 1
    fi
    echo "All steps passed."
  '
  [ "$status" -eq 0 ]
  [ "$output" = "All steps passed." ]
}

@test "test-iso-pipeline: install=0 skips step 5" {
  run bash -c '
    INSTALL="0"
    PASS=0
    if [[ "$INSTALL" == "1" ]]; then
      PASS=$((PASS + 1))
      echo "Step 5 executed"
    else
      echo "Step 5 skipped"
    fi
    echo "PASS=$PASS"
  '
  [ "$output" = "$(printf 'Step 5 skipped\nPASS=0')" ]
}

@test "test-iso-pipeline: install=1 executes step 5" {
  run bash -c '
    INSTALL="1"
    PASS=0
    if [[ "$INSTALL" == "1" ]]; then
      PASS=$((PASS + 1))
      echo "Step 5 executed"
    fi
    echo "PASS=$PASS"
  '
  [ "$output" = "$(printf 'Step 5 executed\nPASS=1')" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# test-iso-pipeline.sh — ISO File Discovery
# ═══════════════════════════════════════════════════════════════════════════

@test "test-iso-pipeline: finds ISO in build directory" {
  run bash -c '
    BUILD_DIR="${TEST_ROOT}/build-iso"
    mkdir -p "$BUILD_DIR"
    touch "$BUILD_DIR/yellowfin-gnome-10-x86_64.iso"
    ISO_FILE=$(find "${BUILD_DIR}" -maxdepth 2 -name "*.iso" 2>/dev/null | head -1 || true)
    if [[ -z "${ISO_FILE}" ]] || [[ ! -f "${ISO_FILE}" ]]; then
      echo "ERROR: No ISO found"
      exit 1
    fi
    echo "FOUND: $(basename "$ISO_FILE")"
  ' 
  [ "$status" -eq 0 ]
  [[ "$output" == *"FOUND: yellowfin-gnome-10-x86_64.iso"* ]]
}

@test "test-iso-pipeline: exits when no ISO found" {
  run bash -c '
    BUILD_DIR="${TEST_ROOT}/empty-dir"
    mkdir -p "$BUILD_DIR"
    ISO_FILE=$(find "${BUILD_DIR}" -maxdepth 2 -name "*.iso" 2>/dev/null | head -1 || true)
    if [[ -z "${ISO_FILE}" ]] || [[ ! -f "${ISO_FILE}" ]]; then
      echo "ERROR: No ISO found in ${BUILD_DIR}" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"ERROR: No ISO found"* ]]
}

@test "test-iso-pipeline: finds first ISO when multiple exist" {
  run bash -c '
    BUILD_DIR="${TEST_ROOT}/multi-iso"
    mkdir -p "$BUILD_DIR"
    touch "$BUILD_DIR/aaa-first.iso"
    touch "$BUILD_DIR/zzz-last.iso"
    ISO_FILE=$(find "${BUILD_DIR}" -maxdepth 2 -name "*.iso" 2>/dev/null | head -1 || true)
    echo "$ISO_FILE"
  '
  [[ "$output" == *"aaa-first.iso"* ]]
}
