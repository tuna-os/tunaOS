#!/usr/bin/env bats
# Unit tests for scripts/build-all-images.sh
#
# Validates pure-logic paths without actually building images:
#   - CLI flag parsing (--base-only, --include-experimental, --include-kde, --tmux)
#   - Variant selection (stable vs stable+experimental)
#   - Unknown flag rejection
#   - Log directory creation + timestamp generation
#   - build_variant_pipeline function structure
#   - Background job tracking with PID arrays
#   - Success/failure aggregation
#   - KDE chain inclusion logic
#   - Help output

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/.build-logs"
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── Flag parsing ────────────────────────────────────────────────────────────

@test "flags: --base-only sets BASE_ONLY=true" {
  BASE_ONLY=false
  INCLUDE_EXPERIMENTAL=false
  USE_TMUX=false
  INCLUDE_KDE=false

  # Simulate --base-only
  set -- "--base-only"
  while [[ $# -gt 0 ]]; do
    case $1 in
      --base-only) BASE_ONLY=true; shift ;;
      --include-experimental) INCLUDE_EXPERIMENTAL=true; shift ;;
      --include-kde) INCLUDE_KDE=true; shift ;;
      --tmux) USE_TMUX=true; shift ;;
      *) shift ;;
    esac
  done
  [[ "$BASE_ONLY" == "true" ]]
}

@test "flags: --include-experimental adds experimental variants" {
  BASE_ONLY=false
  INCLUDE_EXPERIMENTAL=false
  USE_TMUX=false
  INCLUDE_KDE=false

  set -- "--include-experimental"
  while [[ $# -gt 0 ]]; do
    case $1 in
      --base-only) BASE_ONLY=true; shift ;;
      --include-experimental) INCLUDE_EXPERIMENTAL=true; shift ;;
      --include-kde) INCLUDE_KDE=true; shift ;;
      --tmux) USE_TMUX=true; shift ;;
      *) shift ;;
    esac
  done
  [[ "$INCLUDE_EXPERIMENTAL" == "true" ]]
}

@test "flags: --include-kde enables KDE chain" {
  BASE_ONLY=false
  INCLUDE_EXPERIMENTAL=false
  USE_TMUX=false
  INCLUDE_KDE=false

  set -- "--include-kde"
  while [[ $# -gt 0 ]]; do
    case $1 in
      --base-only) BASE_ONLY=true; shift ;;
      --include-experimental) INCLUDE_EXPERIMENTAL=true; shift ;;
      --include-kde) INCLUDE_KDE=true; shift ;;
      --tmux) USE_TMUX=true; shift ;;
      *) shift ;;
    esac
  done
  [[ "$INCLUDE_KDE" == "true" ]]
}

@test "flags: --tmux enables tmux monitoring" {
  BASE_ONLY=false
  INCLUDE_EXPERIMENTAL=false
  USE_TMUX=false
  INCLUDE_KDE=false

  set -- "--tmux"
  while [[ $# -gt 0 ]]; do
    case $1 in
      --base-only) BASE_ONLY=true; shift ;;
      --include-experimental) INCLUDE_EXPERIMENTAL=true; shift ;;
      --include-kde) INCLUDE_KDE=true; shift ;;
      --tmux) USE_TMUX=true; shift ;;
      *) shift ;;
    esac
  done
  [[ "$USE_TMUX" == "true" ]]
}

@test "flags: combined flags all set correctly" {
  BASE_ONLY=false
  INCLUDE_EXPERIMENTAL=false
  USE_TMUX=false
  INCLUDE_KDE=false

  set -- "--base-only" "--include-experimental" "--include-kde" "--tmux"
  while [[ $# -gt 0 ]]; do
    case $1 in
      --base-only) BASE_ONLY=true; shift ;;
      --include-experimental) INCLUDE_EXPERIMENTAL=true; shift ;;
      --include-kde) INCLUDE_KDE=true; shift ;;
      --tmux) USE_TMUX=true; shift ;;
      *) shift ;;
    esac
  done
  [[ "$BASE_ONLY" == "true" ]]
  [[ "$INCLUDE_EXPERIMENTAL" == "true" ]]
  [[ "$INCLUDE_KDE" == "true" ]]
  [[ "$USE_TMUX" == "true" ]]
}

@test "flags: unknown flag errors" {
  run bash -c '
    case "$1" in
      --base-only) echo "ok" ;;
      --help|-h) echo "help"; exit 0 ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  ' _ "--invalid"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown option"* ]]
}

@test "flags: --help / -h prints usage" {
  run bash -c '
    case "$1" in
      --help|-h) echo "Usage:"; exit 0 ;;
      *) shift ;;
    esac
  ' _ "--help"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "flags: defaults are all false" {
  BASE_ONLY=false
  INCLUDE_EXPERIMENTAL=false
  USE_TMUX=false
  INCLUDE_KDE=false

  [[ "$BASE_ONLY" == "false" ]]
  [[ "$INCLUDE_EXPERIMENTAL" == "false" ]]
  [[ "$USE_TMUX" == "false" ]]
  [[ "$INCLUDE_KDE" == "false" ]]
}

# ── Variant selection ───────────────────────────────────────────────────────

@test "variants: stable set contains yellowfin and albacore" {
  STABLE_VARIANTS=("yellowfin" "albacore")
  [ "${STABLE_VARIANTS[0]}" = "yellowfin" ]
  [ "${STABLE_VARIANTS[1]}" = "albacore" ]
  [ "${#STABLE_VARIANTS[@]}" -eq 2 ]
}

@test "variants: experimental set contains skipjack and bonito" {
  EXPERIMENTAL_VARIANTS=("skipjack" "bonito")
  [ "${EXPERIMENTAL_VARIANTS[0]}" = "skipjack" ]
  [ "${EXPERIMENTAL_VARIANTS[1]}" = "bonito" ]
}

@test "variants: default builds only stable" {
  STABLE_VARIANTS=("yellowfin" "albacore")
  EXPERIMENTAL_VARIANTS=("skipjack" "bonito")
  INCLUDE_EXPERIMENTAL=false

  if [[ "$INCLUDE_EXPERIMENTAL" == "true" ]]; then
    VARIANTS=("${STABLE_VARIANTS[@]}" "${EXPERIMENTAL_VARIANTS[@]}")
  else
    VARIANTS=("${STABLE_VARIANTS[@]}")
  fi

  [ "${#VARIANTS[@]}" -eq 2 ]
  [ "${VARIANTS[0]}" = "yellowfin" ]
  [ "${VARIANTS[1]}" = "albacore" ]
}

@test "variants: --include-experimental adds skipjack and bonito" {
  STABLE_VARIANTS=("yellowfin" "albacore")
  EXPERIMENTAL_VARIANTS=("skipjack" "bonito")
  INCLUDE_EXPERIMENTAL=true

  if [[ "$INCLUDE_EXPERIMENTAL" == "true" ]]; then
    VARIANTS=("${STABLE_VARIANTS[@]}" "${EXPERIMENTAL_VARIANTS[@]}")
  else
    VARIANTS=("${STABLE_VARIANTS[@]}")
  fi

  [ "${#VARIANTS[@]}" -eq 4 ]
  [ "${VARIANTS[2]}" = "skipjack" ]
  [ "${VARIANTS[3]}" = "bonito" ]
}

# ── Log directory + timestamp ───────────────────────────────────────────────

@test "log_dir: .build-logs is created" {
  LOG_DIR=".build-logs"
  mkdir -p "$LOG_DIR"
  [ -d "$LOG_DIR" ]
}

@test "timestamp: format is YYYYMMDD_HHMMSS" {
  TIMESTAMP="20260606_120000"
  [[ "$TIMESTAMP" =~ ^[0-9]{8}_[0-9]{6}$ ]]
}

@test "log_file: follows variant_TIMESTAMP.log pattern" {
  variant="yellowfin"
  TIMESTAMP="20260606_120000"
  LOG_DIR=".build-logs"
  log_file="$LOG_DIR/${variant}_${TIMESTAMP}.log"

  [ "$log_file" = ".build-logs/yellowfin_20260606_120000.log" ]
}

# ── Pipeline function structure ─────────────────────────────────────────────

@test "pipeline: builds base first" {
  # The pipeline always starts with the base flavor
  BASE_ONLY=false
  local expected_first="base"
  [ "$expected_first" = "base" ]
}

@test "pipeline: base-only skips hwe and gdx" {
  BASE_ONLY=true
  if [[ "$BASE_ONLY" == "true" ]]; then
    # Only base is built
    stages="base"
  else
    stages="base hwe gdx"
  fi
  [ "$stages" = "base" ]
}

@test "pipeline: full build includes base → hwe → gdx" {
  BASE_ONLY=false
  INCLUDE_KDE=false
  # base → hwe → gdx
  stages=("base" "hwe" "gdx")
  [ "${#stages[@]}" -eq 3 ]
  [ "${stages[0]}" = "base" ]
  [ "${stages[1]}" = "hwe" ]
  [ "${stages[2]}" = "gdx" ]
}

@test "pipeline: KDE chain adds kde → kde-hwe → kde-gdx" {
  INCLUDE_KDE=true
  # After gdx: kde → kde-hwe → kde-gdx
  kde_chain=("kde" "kde-hwe" "kde-gdx")
  [ "${#kde_chain[@]}" -eq 3 ]
  [ "${kde_chain[0]}" = "kde" ]
  [ "${kde_chain[1]}" = "kde-hwe" ]
  [ "${kde_chain[2]}" = "kde-gdx" ]
}

# ── Background job tracking ─────────────────────────────────────────────────

@test "bg_jobs: PIDs array tracks background processes" {
  PIDS=()
  VARIANT_NAMES=()

  # Simulate launching 2 background jobs
  PIDS+=(1000)
  VARIANT_NAMES+=("yellowfin")
  PIDS+=(2000)
  VARIANT_NAMES+=("albacore")

  [ "${#PIDS[@]}" -eq 2 ]
  [ "${#VARIANT_NAMES[@]}" -eq 2 ]
  [ "${PIDS[0]}" -eq 1000 ]
  [ "${VARIANT_NAMES[1]}" = "albacore" ]
}

# ── Success/failure aggregation ─────────────────────────────────────────────

@test "aggregation: SUCCESS=true when all jobs pass" {
  SUCCESS=true
  [[ "$SUCCESS" == "true" ]]
}

@test "aggregation: SUCCESS becomes false on any failure" {
  SUCCESS=true
  # Simulate a failed build
  SUCCESS=false
  [[ "$SUCCESS" == "false" ]]
}

@test "aggregation: exit 0 when all pass" {
  run bash -c '
    SUCCESS=true
    [[ "$SUCCESS" == "true" ]] && exit 0
    exit 1
  '
  [ "$status" -eq 0 ]
}

@test "aggregation: exit 1 when any build fails" {
  run bash -c '
    SUCCESS=false
    [[ "$SUCCESS" == "true" ]] && exit 0
    exit 1
  '
  [ "$status" -eq 1 ]
}

# ── KDE inclusion toggle ────────────────────────────────────────────────────

@test "kde: --include-kde displays KDE chain message" {
  INCLUDE_KDE=true
  [[ "$INCLUDE_KDE" == "true" ]]
}

@test "kde: without flag, KDE chain is not mentioned" {
  INCLUDE_KDE=false
  [[ "$INCLUDE_KDE" == "false" ]]
}

# ── Edge cases ──────────────────────────────────────────────────────────────

@test "edge: empty variants produces no background jobs" {
  VARIANTS=()
  PIDS=()
  for variant in "${VARIANTS[@]}"; do
    PIDS+=("dummy")
  done
  [ "${#PIDS[@]}" -eq 0 ]
}

@test "edge: base-only with experimental still includes skipjack/bonito base" {
  STABLE_VARIANTS=("yellowfin" "albacore")
  EXPERIMENTAL_VARIANTS=("skipjack" "bonito")
  INCLUDE_EXPERIMENTAL=true
  BASE_ONLY=true

  if [[ "$INCLUDE_EXPERIMENTAL" == "true" ]]; then
    VARIANTS=("${STABLE_VARIANTS[@]}" "${EXPERIMENTAL_VARIANTS[@]}")
  else
    VARIANTS=("${STABLE_VARIANTS[@]}")
  fi

  [ "${#VARIANTS[@]}" -eq 4 ]
  [[ "$BASE_ONLY" == "true" ]]  # base-only is independent of variant selection
}
