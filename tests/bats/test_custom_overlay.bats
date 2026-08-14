#!/usr/bin/env bats
# Tests for custom/ overlay pipeline scripts and Justfile integration

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "Containerfile.custom exists" {
  run test -f "${REPO_ROOT}/Containerfile.custom"
  [ "$status" -eq 0 ]
}

@test "build_scripts/apply-custom.sh exists and is executable" {
  run test -f "${REPO_ROOT}/build_scripts/apply-custom.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/apply-custom.sh passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/apply-custom.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "custom directory structure is present" {
  run test -d "${REPO_ROOT}/custom"
  [ "$status" -eq 0 ]
  run test -f "${REPO_ROOT}/custom/image.yaml"
  [ "$status" -eq 0 ]
  run test -f "${REPO_ROOT}/custom/packages.yaml"
  [ "$status" -eq 0 ]
}

@test "Justfile contains custom recipes" {
  local recipe_file="${REPO_ROOT}/Justfile"
  if ! grep -q "build-custom" "$recipe_file" ||
    ! grep -q "check-custom" "$recipe_file" ||
    ! grep -q "run-custom-vm" "$recipe_file" ||
    ! grep -q "custom-iso" "$recipe_file"; then
    recipe_file="${REPO_ROOT}/just/custom-overlay.just"
  fi

  for recipe in build-custom check-custom run-custom-vm custom-iso; do
    run grep -q "$recipe" "$recipe_file"
    [ "$status" -eq 0 ]
  done
}
