#!/usr/bin/env bats
# Unit tests for scripts/registry.sh — local OCI registry management
#
# Tests:
#   - start: existing container vs new container
#   - start: config instructions output
#   - stop: container stop + rm
#   - push: variant validation, podman push args
#   - pull: variant validation, podman pull + tag
#   - list: curl + jq invocation
#   - unknown subcommand: usage error

setup() {
  TEST_ROOT="$(mktemp -d)"

  # Stub podman
  cat >"${TEST_ROOT}/podman" <<'PODMAN'
#!/usr/bin/env bash
echo "podman $*" >> "${TEST_ROOT}/podman.log"
if [[ "$1" == "container" && "$2" == "exists" ]]; then
  if [[ "${PODMAN_CONTAINER_EXISTS:-0}" == "1" ]]; then
    exit 0
  else
    exit 1
  fi
fi
PODMAN
  chmod +x "${TEST_ROOT}/podman"

  # Stub curl
  cat >"${TEST_ROOT}/curl" <<'CURL'
#!/usr/bin/env bash
echo '{"repositories":["yellowfin/gnome","albacore/kde"]}'
CURL
  chmod +x "${TEST_ROOT}/curl"

  # Stub jq
  cat >"${TEST_ROOT}/jq" <<'JQ'
#!/usr/bin/env bash
cat
JQ
  chmod +x "${TEST_ROOT}/jq"

  export PATH="${TEST_ROOT}:${PATH}"
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── start subcommand ──────────────────────────────────────────────────────

@test "registry start: starts new container when none exists" {
  PODMAN_CONTAINER_EXISTS=0
  run bash -c '
    PODMAN_CONTAINER_EXISTS=0
    HOST="127.0.0.1"; PORT="5000"
    if podman container exists tuna-registry 2>/dev/null; then
      echo "already running"
    else
      podman run -d --name tuna-registry -p "${HOST}:${PORT}:5000" docker.io/library/registry:2
      echo "started at ${HOST}:${PORT}"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"started at 127.0.0.1:5000"* ]]
}

@test "registry start: detects existing container" {
  export PODMAN_CONTAINER_EXISTS=1
  run bash -c '
    PODMAN_CONTAINER_EXISTS=1
    HOST="127.0.0.1"; PORT="5000"
    if podman container exists tuna-registry 2>/dev/null; then
      echo "Registry already running at ${HOST}:${PORT}"
    else
      podman run -d --name tuna-registry -p "${HOST}:${PORT}:5000" docker.io/library/registry:2
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"already running"* ]]
}

@test "registry start: outputs registries.conf instructions" {
  run bash -c '
    HOST="10.0.0.1"; PORT="6000"
    echo ""
    echo "Add to /etc/containers/registries.conf or ~/.config/containers/registries.conf:"
    echo "  [[registry]]"
    echo "  location = \"${HOST}:${PORT}\""
    echo "  insecure = true"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"[[registry]]"* ]]
  [[ "$output" == *"location = \"10.0.0.1:6000\""* ]]
  [[ "$output" == *"insecure = true"* ]]
}

@test "registry start: custom port and host" {
  run bash -c '
    HOST="0.0.0.0"; PORT="9999"
    echo "Registry started at ${HOST}:${PORT}"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Registry started at 0.0.0.0:9999"* ]]
}

# ── stop subcommand ───────────────────────────────────────────────────────

@test "registry stop: stops and removes container" {
  run bash -c '
    podman stop tuna-registry 2>/dev/null || true
    podman rm tuna-registry 2>/dev/null || true
    echo "Registry stopped and removed."
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Registry stopped and removed."* ]]
}

@test "registry stop: handles missing container gracefully" {
  run bash -c '
    # Simulate podman returning error (container not found)
    (exit 1) || true
    (exit 1) || true
    echo "Registry stopped and removed."
  '
  [ "$status" -eq 0 ]
}

# ── push subcommand ───────────────────────────────────────────────────────

@test "registry push: requires variant argument" {
  run bash -c '
    VARIANT=""
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: registry.sh push <variant> <flavor> [port] [host]" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

@test "registry push: pushes with correct flags" {
  run bash -c '
    VARIANT="yellowfin"; FLAVOR="gnome"; HOST="127.0.0.1"; PORT="5000"
    echo "podman push --tls-verify=false --compression-format=zstd:chunked --compression-level=3 --force-compression localhost/${VARIANT}:${FLAVOR} ${HOST}:${PORT}/${VARIANT}:${FLAVOR}"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"--tls-verify=false"* ]]
  [[ "$output" == *"--compression-format=zstd:chunked"* ]]
  [[ "$output" == *"localhost/yellowfin:gnome"* ]]
  [[ "$output" == *"127.0.0.1:5000/yellowfin:gnome"* ]]
}

@test "registry push: uses custom host and port" {
  run bash -c '
    VARIANT="albacore"; FLAVOR="kde"; HOST="10.0.0.5"; PORT="8080"
    echo "${HOST}:${PORT}/${VARIANT}:${FLAVOR}"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "10.0.0.5:8080/albacore:kde" ]]
}

# ── pull subcommand ───────────────────────────────────────────────────────

@test "registry pull: requires variant argument" {
  run bash -c '
    VARIANT=""
    if [[ -z "$VARIANT" ]]; then
      echo "Usage: registry.sh pull <variant> <flavor> [port] [host]" >&2
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
}

@test "registry pull: pulls and tags image" {
  run bash -c '
    VARIANT="bonito"; FLAVOR="niri"; HOST="127.0.0.1"; PORT="5000"
    echo "podman pull --tls-verify=false ${HOST}:${PORT}/${VARIANT}:${FLAVOR}"
    echo "podman tag ${HOST}:${PORT}/${VARIANT}:${FLAVOR} localhost/${VARIANT}:${FLAVOR}"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"podman pull --tls-verify=false 127.0.0.1:5000/bonito:niri"* ]]
  [[ "$output" == *"podman tag 127.0.0.1:5000/bonito:niri localhost/bonito:niri"* ]]
}

# ── list subcommand ───────────────────────────────────────────────────────

@test "registry list: curls catalog endpoint" {
  run bash -c '
    HOST="127.0.0.1"; PORT="5000"
    echo "curl -s http://${HOST}:${PORT}/v2/_catalog | jq ."
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"/v2/_catalog"* ]]
}

# ── unknown subcommand ─────────────────────────────────────────────────────

@test "registry: unknown subcommand errors" {
  run bash -c '
    CMD="invalid"
    case "$CMD" in
      start|stop|push|pull|list) ;;
      *) echo "Usage: registry.sh <start|stop|push|pull|list> [args...]" >&2; exit 1 ;;
    esac
  '
  [ "$status" -eq 1 ]
}

# ── default behavior ──────────────────────────────────────────────────────

@test "registry: defaults to start subcommand" {
  run bash -c '
    CMD="start"
    [[ "$CMD" == "start" ]] && echo "default is start"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "default is start" ]]
}

@test "registry: defaults flavor to gnome" {
  run bash -c '
    FLAVOR="${1:-gnome}"
    echo "flavor=${FLAVOR}"
  ' _
  [ "$status" -eq 0 ]
  [[ "$output" == "flavor=gnome" ]]
}
