#!/usr/bin/env bats
# BATS tests for scripts that still lack test coverage:
#   pipeline-overview.sh, run-vm.sh, setup-build-cache.sh,
#   simulate-matrix.sh, sync-build-cache.sh

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# ═══════════════════════════════════════════════════════════════════════════
# pipeline-overview.sh — Runtime-patched pipeline display
# ═══════════════════════════════════════════════════════════════════════════

@test "pipeline-overview.sh: exists" {
  run test -f "${REPO_ROOT}/scripts/pipeline-overview.sh"
  [ "$status" -eq 0 ]
}

@test "pipeline-overview.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/scripts/pipeline-overview.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "pipeline-overview.sh: uses __STATUS_DIR__ placeholder" {
  run grep '__STATUS_DIR__' "${REPO_ROOT}/scripts/pipeline-overview.sh"
  [ "$status" -eq 0 ]
}

@test "pipeline-overview.sh: uses __STAGE_NAME__ placeholder" {
  run grep '__STAGE_NAME__' "${REPO_ROOT}/scripts/pipeline-overview.sh"
  [ "$status" -eq 0 ]
}

@test "pipeline-overview.sh: defines SPINNER_FRAMES" {
  run grep 'SPINNER_FRAMES=' "${REPO_ROOT}/scripts/pipeline-overview.sh"
  [ "$status" -eq 0 ]
}

@test "pipeline-overview.sh: has ASCII color escape definitions" {
  run grep 'BOLD=' "${REPO_ROOT}/scripts/pipeline-overview.sh"
  [ "$status" -eq 0 ]
}

@test "pipeline-overview.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/scripts/pipeline-overview.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# run-vm.sh — VM run/demo helpers
# ═══════════════════════════════════════════════════════════════════════════

@test "run-vm.sh: exists and is executable" {
  run test -x "${REPO_ROOT}/scripts/run-vm.sh"
  [ "$status" -eq 0 ]
}

@test "run-vm.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/scripts/run-vm.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "run-vm.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/scripts/run-vm.sh"
  [ "$status" -eq 0 ]
}

@test "run-vm.sh: fails when called with no arguments" {
  run bash "${REPO_ROOT}/scripts/run-vm.sh"
  [ "$status" -ne 0 ]
}

@test "run-vm.sh: fails with unknown subcommand" {
  run bash "${REPO_ROOT}/scripts/run-vm.sh" nonexistent-subcommand
  [ "$status" -ne 0 ]
}

@test "run-vm.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/scripts/run-vm.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# setup-build-cache.sh — RPM cache setup
# ═══════════════════════════════════════════════════════════════════════════

@test "setup-build-cache.sh: exists" {
  run test -f "${REPO_ROOT}/scripts/setup-build-cache.sh"
  [ "$status" -eq 0 ]
}

@test "setup-build-cache.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/scripts/setup-build-cache.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "setup-build-cache.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/scripts/setup-build-cache.sh"
  [ "$status" -eq 0 ]
}

@test "setup-build-cache.sh: prints usage when called with no arguments" {
  run bash "${REPO_ROOT}/scripts/setup-build-cache.sh"
  [ "$status" -ne 0 ]
  [[ "$output" =~ Usage ]]
}

@test "setup-build-cache.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/scripts/setup-build-cache.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# simulate-matrix.sh — Build matrix simulation
# ═══════════════════════════════════════════════════════════════════════════

@test "simulate-matrix.sh: exists" {
  run test -f "${REPO_ROOT}/scripts/simulate-matrix.sh"
  [ "$status" -eq 0 ]
}

@test "simulate-matrix.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/scripts/simulate-matrix.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "simulate-matrix.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/scripts/simulate-matrix.sh"
  [ "$status" -eq 0 ]
}

@test "simulate-matrix.sh: runs successfully with build-config.yml" {
  run bash "${REPO_ROOT}/scripts/simulate-matrix.sh"
  [ "$status" -eq 0 ]
}

@test "simulate-matrix.sh: fails when build-config.yml is missing" {
  # "Missing" now means the resolved config does not exist, not "the caller's
  # CWD happens not to contain one". Before scripts/lib/build-config.sh this
  # test cd'd to a temp dir, which only worked because the script read a
  # relative path — the CWD-dependence this seam deliberately removes.
  run env TUNAOS_BUILD_CONFIG="${BATS_TEST_TMPDIR}/absent.yml" bash "${REPO_ROOT}/scripts/simulate-matrix.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"build config not found"* ]]
}

@test "simulate-matrix.sh: resolves its config from any working directory" {
  # The inverse of the assertion above, and the actual point of the change:
  # running from an unrelated CWD must now succeed.
  run bash -c "cd \$(mktemp -d) && bash ${REPO_ROOT}/scripts/simulate-matrix.sh"
  [ "$status" -eq 0 ]
}

@test "simulate-matrix.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/scripts/simulate-matrix.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# sync-build-cache.sh — Cache dedup sync
# ═══════════════════════════════════════════════════════════════════════════

@test "sync-build-cache.sh: exists" {
  run test -f "${REPO_ROOT}/scripts/sync-build-cache.sh"
  [ "$status" -eq 0 ]
}

@test "sync-build-cache.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/scripts/sync-build-cache.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "sync-build-cache.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/scripts/sync-build-cache.sh"
  [ "$status" -eq 0 ]
}

@test "sync-build-cache.sh: prints usage when called with no arguments" {
  run bash "${REPO_ROOT}/scripts/sync-build-cache.sh"
  [ "$status" -ne 0 ]
  [[ "$output" =~ Usage ]]
}

@test "sync-build-cache.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/scripts/sync-build-cache.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}
