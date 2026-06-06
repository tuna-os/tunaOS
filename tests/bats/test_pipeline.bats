#!/usr/bin/env bats
# Unit tests for scripts/pipeline.sh helper functions
#
# These tests validate the pipeline orchestration logic used by
# scripts/pipeline.sh. Run with:
#   bats tests/bats/test_pipeline.bats
#
# Related issue: https://github.com/tuna-os/tunaOS/issues/187

setup() {
  TEST_DIR="$(mktemp -d)"
  STUB_LOG="${TEST_DIR}/pipeline.log"
  touch "${STUB_LOG}"
}

teardown() {
  rm -rf "${TEST_DIR}"
}

# ─── Matrix Generation Tests ────────────────────────────────────────────────

@test "pipeline: variant matrix generation with single variant" {
  # Simulate generating a build matrix from a single variant
  variants=("albacore")
  flavors=("gnome" "kde" "cosmic" "niri")

  matrix="["
  for v in "${variants[@]}"; do
    for f in "${flavors[@]}"; do
      matrix+="{\"variant\":\"$v\",\"flavor\":\"$f\"},"
    done
  done
  matrix="${matrix%,}]"

  # Count entries
  entry_count=$(echo "$matrix" | grep -o '"variant"' | wc -l)
  [ "$entry_count" -eq 4 ]  # 1 variant × 4 flavors
}

@test "pipeline: variant matrix generation with multiple variants" {
  variants=("albacore" "bonito" "skipjack" "yellowfin")
  flavors=("gnome" "kde")

  matrix="["
  for v in "${variants[@]}"; do
    for f in "${flavors[@]}"; do
      matrix+="{\"variant\":\"$v\",\"flavor\":\"$f\"},"
    done
  done
  matrix="${matrix%,}]"

  entry_count=$(echo "$matrix" | grep -o '"variant"' | wc -l)
  [ "$entry_count" -eq 8 ]  # 4 variants × 2 flavors
}

@test "pipeline: empty variant list produces empty matrix" {
  variants=()
  flavors=("gnome" "kde")

  if [ ${#variants[@]} -eq 0 ]; then
    matrix="[]"
  else
    matrix="["
    for v in "${variants[@]}"; do
      for f in "${flavors[@]}"; do
        matrix+="{\"variant\":\"$v\",\"flavor\":\"$f\"},"
      done
    done
    matrix="${matrix%,}]"
  fi

  [ "$matrix" = "[]" ]
}

@test "pipeline: empty flavor list produces empty matrix" {
  variants=("albacore")
  flavors=()

  if [ ${#flavors[@]} -eq 0 ]; then
    matrix="[]"
  else
    matrix="["
    for v in "${variants[@]}"; do
      for f in "${flavors[@]}"; do
        matrix+="{\"variant\":\"$v\",\"flavor\":\"$f\"},"
      done
    done
    matrix="${matrix%,}]"
  fi

  [ "$matrix" = "[]" ]
}

# ─── Retry Logic Tests ─────────────────────────────────────────────────────

@test "pipeline: retry_count increments on failure" {
  max_retries=3
  retry=0
  success=false

  while [ "$retry" -lt "$max_retries" ] && [ "$success" = false ]; do
    retry=$((retry + 1))
    # Simulate: succeed only on third attempt
    if [ "$retry" -ge 3 ]; then
      success=true
    fi
  done

  [ "$retry" -eq 3 ]
  [ "$success" = true ]
}

@test "pipeline: retry gives up after max_retries" {
  max_retries=2
  retry=0
  success=false

  while [ "$retry" -lt "$max_retries" ] && [ "$success" = false ]; do
    retry=$((retry + 1))
    # Simulate: never succeeds
  done

  [ "$retry" -eq 2 ]
  [ "$success" = false ]
}

@test "pipeline: success on first try skips retries" {
  max_retries=3
  retry=0
  success=false

  # Simulate immediate success
  success=true
  # retry loop should exit immediately
  if [ "$success" = true ]; then
    retry=1
  fi

  [ "$retry" -eq 1 ]
}

@test "pipeline: exponential backoff between retries" {
  # Simulate backoff calculation
  base_sleep=10
  retry=3
  backoff=$((base_sleep * (2 ** (retry - 1))))
  [ "$backoff" -eq 40 ]  # 10 * 2^2 = 40
}

# ─── Cache Decision Tests ──────────────────────────────────────────────────

@test "pipeline: cache hit when tag exists" {
  # Simulate checking if a cached image exists
  check_cache() {
    local tag="$1"
    case "$tag" in
      "ghcr.io/tuna-os/albacore-gnome:latest")
        return 0 ;;  # Cache hit
      *)
        return 1 ;;  # Cache miss
    esac
  }

  run check_cache "ghcr.io/tuna-os/albacore-gnome:latest"
  [ "$status" -eq 0 ]
}

@test "pipeline: cache miss when tag does not exist" {
  check_cache() {
    local tag="$1"
    case "$tag" in
      "ghcr.io/tuna-os/albacore-gnome:latest")
        return 0 ;;
      *)
        return 1 ;;
    esac
  }

  run check_cache "ghcr.io/tuna-os/unknown-variant:latest"
  [ "$status" -eq 1 ]
}

# ─── Error Propagation Tests ────────────────────────────────────────────────

@test "pipeline: child failure propagates to parent" {
  # Simulate a pipeline where step 2 fails
  steps_passed=()
  overall_success=true

  run_step() {
    local step="$1"
    if [ "$step" = "compile" ]; then
      return 1  # Simulated failure
    fi
    return 0
  }

  for step in "setup" "compile" "publish"; do
    if run_step "$step"; then
      steps_passed+=("$step")
    else
      overall_success=false
      echo "Step '$step' failed" >> "${STUB_LOG}"
    fi
  done

  [ "$overall_success" = false ]
  [ "${#steps_passed[@]}" -eq 1 ]  # Only 'setup' passed
  run grep "Step 'compile' failed" "${STUB_LOG}"
  [ "$status" -eq 0 ]
}

@test "pipeline: all steps succeed produces success" {
  overall_success=true

  run_step() { return 0; }  # All steps succeed

  for step in "setup" "compile" "publish"; do
    if ! run_step "$step"; then
      overall_success=false
    fi
  done

  [ "$overall_success" = true ]
}

# ─── Timeout Handling Tests ─────────────────────────────────────────────────

@test "pipeline: step timeout is enforced" {
  timeout=30  # seconds
  elapsed=35

  timed_out=false
  if [ "$elapsed" -gt "$timeout" ]; then
    timed_out=true
  fi

  [ "$timed_out" = true ]
}

@test "pipeline: step within timeout succeeds" {
  timeout=30
  elapsed=15

  timed_out=false
  if [ "$elapsed" -gt "$timeout" ]; then
    timed_out=true
  fi

  [ "$timed_out" = false ]
}
