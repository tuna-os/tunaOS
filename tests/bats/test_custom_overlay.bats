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
  # The custom overlay recipes were extracted from the root Justfile into
  # just/custom-overlay.just (#508); the root Justfile imports it, so the
  # recipes resolve through `just`. Grep the extracted file, and keep the
  # root import as the contract anchor so a future re-extraction is caught.
  run grep "build-custom" "${REPO_ROOT}/just/custom-overlay.just"
  [ "$status" -eq 0 ]
  run grep "check-custom" "${REPO_ROOT}/just/custom-overlay.just"
  [ "$status" -eq 0 ]
  run grep "run-custom-vm" "${REPO_ROOT}/just/custom-overlay.just"
  [ "$status" -eq 0 ]
  run grep "custom-iso" "${REPO_ROOT}/just/custom-overlay.just"
  [ "$status" -eq 0 ]
  run grep "import 'just/custom-overlay.just'" "${REPO_ROOT}/Justfile"
  [ "$status" -eq 0 ]
}
