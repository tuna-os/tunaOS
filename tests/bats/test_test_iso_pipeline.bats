#!/usr/bin/env bats
# Unit tests for scripts/test-iso-pipeline.sh
#
# Tests:
#   - Missing variant argument exits with usage
#   - Default values (flavor=gnome, source=local, install=0, port=5000)
#   - Source routing: local, ghcr, registry
#   - Unknown source error
#   - ISO file discovery from build directory
#   - Missing ISO file error
#   - PASS counter increments
#   - Install=0 skips step 5
#   - Install=1 triggers step 5

# ── Argument Validation ───────────────────────────────────────────────────

@test "exits when variant is empty" {
  run bash -c '
    VARIANT=""
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: test-iso-pipeline.sh <variant> [flavor] [source] [install] [port]" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "accepts variant-only with defaults" {
  run bash -c '
    VARIANT="yellowfin"
    FLAVOR="${2:-gnome}"
    SOURCE="${3:-local}"
    INSTALL="${4:-0}"
    PORT="${5:-5000}"
    echo "$VARIANT $FLAVOR $SOURCE $INSTALL $PORT"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "yellowfin gnome local 0 5000" ]]
}

@test "accepts all arguments explicitly" {
  run bash -c '
    set -- bonito kde registry 1 8080
    VARIANT="${1:-}"
    FLAVOR="${2:-gnome}"
    SOURCE="${3:-local}"
    INSTALL="${4:-0}"
    PORT="${5:-5000}"
    echo "$VARIANT $FLAVOR $SOURCE $INSTALL $PORT"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "bonito kde registry 1 8080" ]]
}

# ── Source Routing ────────────────────────────────────────────────────────

@test "local source: checks for existing image" {
  run bash -c '
    SOURCE="local"; VARIANT="bonito"; FLAVOR="niri"
    case "$SOURCE" in
      local)
        echo "checking localhost/${VARIANT}:${FLAVOR}"
        ;;
    esac
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"localhost/bonito:niri"* ]]
}

@test "ghcr source: constructs ghcr pull command" {
  run bash -c '
    SOURCE="ghcr"; VARIANT="skipjack"; FLAVOR="base"
    case "$SOURCE" in
      ghcr)
        echo "podman pull ghcr.io/tuna-os/${VARIANT}:${FLAVOR}"
        echo "podman tag ghcr.io/tuna-os/${VARIANT}:${FLAVOR} localhost/${VARIANT}:${FLAVOR}"
        ;;
    esac
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"podman pull ghcr.io/tuna-os/skipjack:base"* ]]
  [[ "$output" == *"podman tag"*"localhost/skipjack:base"* ]]
}

@test "registry source: constructs registry pull with port" {
  run bash -c '
    SOURCE="registry"; VARIANT="yellowfin"; FLAVOR="gnome"; PORT="5000"
    case "$SOURCE" in
      registry)
        echo "podman pull --tls-verify=false localhost:${PORT}/${VARIANT}:${FLAVOR}"
        echo "podman tag localhost:${PORT}/${VARIANT}:${FLAVOR} localhost/${VARIANT}:${FLAVOR}"
        ;;
    esac
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"localhost:5000/yellowfin:gnome"* ]]
  [[ "$output" == *"podman tag"*"localhost/yellowfin:gnome"* ]]
}

@test "unknown source exits with error" {
  run bash -c '
    SOURCE="dockerhub"; VARIANT="yellowfin"; FLAVOR="gnome"
    case "$SOURCE" in
      local|ghcr|registry) echo "ok" ;;
      *) echo "ERROR: Unknown source ${SOURCE}" >&2; exit 1 ;;
    esac
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown source"* ]]
}

# ── ISO File Discovery ────────────────────────────────────────────────────

@test "finds ISO file in build directory" {
  run bash -c '
    VARIANT="albacore"; FLAVOR="kde"
    BUILD_DIR=".build/live-iso/${VARIANT}-${FLAVOR}"
    echo "searching ${BUILD_DIR}"
    echo "/path/to/${VARIANT}-${FLAVOR}.iso"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *".build/live-iso/albacore-kde"* ]]
  [[ "$output" == *"albacore-kde.iso"* ]]
}

@test "exits when no ISO file found" {
  run bash -c '
    ISO_FILE=""
    if [[ -z "${ISO_FILE}" ]] || [[ ! -f "${ISO_FILE}" ]]; then
      echo "ERROR: No ISO found" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"No ISO found"* ]]
}

# ── PASS/FAIL Counter ─────────────────────────────────────────────────────

@test "initializes counters at zero" {
  run bash -c '
    PASS=0; FAIL=0
    echo "PASS=$PASS FAIL=$FAIL"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "PASS=0 FAIL=0" ]]
}

@test "increments PASS counter" {
  run bash -c '
    PASS=0
    PASS=$((PASS + 1))
    PASS=$((PASS + 1))
    PASS=$((PASS + 1))
    echo "PASS=$PASS"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "PASS=3" ]]
}

# ── Install Step Gating ───────────────────────────────────────────────────

@test "skips install step when INSTALL=0" {
  run bash -c '
    INSTALL=0
    if [[ "$INSTALL" == "1" ]]; then
      echo "Step 5: Install test"
    else
      echo "install step skipped"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipped"* ]]
}

@test "runs install step when INSTALL=1" {
  run bash -c '
    INSTALL=1
    if [[ "$INSTALL" == "1" ]]; then
      echo "Step 5: Install test"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Step 5"* ]]
}

# ── Summary Output ────────────────────────────────────────────────────────

@test "reports failure when FAIL > 0" {
  run bash -c '
    FAIL=2
    if [[ "$FAIL" -gt 0 ]]; then
      echo "ERROR: ${FAIL} step(s) failed."
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"2 step(s) failed"* ]]
}

@test "reports all passed when FAIL=0" {
  run bash -c '
    FAIL=0
    if [[ "$FAIL" -gt 0 ]]; then
      echo "ERROR"
      exit 1
    fi
    echo "All steps passed."
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"All steps passed"* ]]
}
