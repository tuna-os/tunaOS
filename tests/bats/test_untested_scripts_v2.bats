#!/usr/bin/env bats
# BATS tests for scripts that still lack test coverage:
#   compare-with-upstream.sh, pipeline-overview.sh, run-vm.sh,
#   setup-build-cache.sh, simulate-matrix.sh, sync-build-cache.sh

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# ═══════════════════════════════════════════════════════════════════════════
# compare-with-upstream.sh
# ═══════════════════════════════════════════════════════════════════════════

@test "compare-with-upstream.sh: exists" {
  run test -f "${REPO_ROOT}/scripts/compare-with-upstream.sh"
  [ "$status" -eq 0 ]
}

@test "compare-with-upstream.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/scripts/compare-with-upstream.sh"
  [[ "$output" =~ ^#!/.*bash ]] || [[ "$output" =~ ^#!/.*sh ]]
}

@test "compare-with-upstream.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/scripts/compare-with-upstream.sh"
  [ "$status" -eq 0 ]
}

@test "compare-with-upstream.sh: fails with usage when called with no arguments" {
  run bash "${REPO_ROOT}/scripts/compare-with-upstream.sh"
  [ "$status" -ne 0 ]
  [[ "$output" =~ Usage ]]
}

@test "compare-with-upstream.sh: fails when called with variant only" {
  run bash "${REPO_ROOT}/scripts/compare-with-upstream.sh" skipjack
  [ "$status" -ne 0 ]
  [[ "$output" =~ Usage ]]
}

@test "compare-with-upstream.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/scripts/compare-with-upstream.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

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
  run bash -c "cd \$(mktemp -d) && bash ${REPO_ROOT}/scripts/simulate-matrix.sh 2>/dev/null; exit \$?"
  [ "$status" -ne 0 ]
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
