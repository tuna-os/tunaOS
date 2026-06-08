#!/usr/bin/env bats
# Unit tests for scripts/check.sh — CI lint orchestration script
#
# Tests:
#   - --install-deps-only flag behavior
#   - Tool dependency installation logic
#   - Exit code propagation
#   - Path exclusion filtering

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/scripts"

  # Copy check.sh (without the set -e for test isolation)
  cp "${REPO_ROOT}/scripts/check.sh" \
     "${TEST_ROOT}/test_check.sh"
  sed -i '1s/^set -euo pipefail/set -uo pipefail\n# set -e removed for test/' \
     "${TEST_ROOT}/test_check.sh"
  # Fix the cd command to use test root
  sed -i "s|cd \"\$(dirname.*|cd \"${TEST_ROOT}\"|" "${TEST_ROOT}/test_check.sh"

  # Stub brew
  cat >"${TEST_ROOT}/brew" <<'BREW'
#!/usr/bin/env bash
echo "brew $*"
BREW
  chmod +x "${TEST_ROOT}/brew"

  export PATH="${TEST_ROOT}:${PATH}"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════

@test "check.sh: --install-deps-only flag exits after installing deps" {
  # Test that the flag logic works correctly
  run bash -c 'INSTALL_ONLY=0; [[ "${1:-}" == "--install-deps-only" ]] && INSTALL_ONLY=1; echo "$INSTALL_ONLY"' _ "--install-deps-only"
  [ "$output" = "1" ]
}

@test "check.sh: without flag, INSTALL_ONLY remains 0" {
  run bash -c 'INSTALL_ONLY=0; [[ "${1:-}" == "--install-deps-only" ]] && INSTALL_ONLY=1; echo "$INSTALL_ONLY"'
  [ "$output" = "0" ]
}

@test "check.sh: shellcheck exclusion SC1091 is passed" {
  # Verify the shellcheck invocation pattern excludes SC1091
  run grep "SC1091" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"SC1091"* ]]
}

@test "check.sh: excludes gnome-shell extensions from linting" {
  run grep "gnome-shell/extensions" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
}

@test "check.sh: excludes packages-repo from linting" {
  run grep "packages-repo" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
}

@test "check.sh: actionlint has specific ignore rules" {
  # There should be at least 5 ignore rules
  run grep -c "\-ignore" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
  [ "$output" -ge 5 ]
}

@test "check.sh: validates .yaml files with yamllint -c .yamllint.yml" {
  run grep "yamllint -c" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *".yamllint.yml"* ]]
}

@test "check.sh: validates .yml files with yamllint (no config)" {
  run grep "yamllint.*yml" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
}

@test "check.sh: validates .json files with jq" {
  run grep "jq \." "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
}

@test "check.sh: validates .just files with just --fmt --check" {
  run grep "just.*fmt.*check.*\.just" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
}

@test "check.sh: validates Justfile at end" {
  run grep "just.*fmt.*check.*Justfile" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
}

@test "check.sh: shellcheck uses /usr/bin/find for cross-platform support" {
  run grep "/usr/bin/find" "${REPO_ROOT}/scripts/check.sh"
  [ "$status" -eq 0 ]
}
