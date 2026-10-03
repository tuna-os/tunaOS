#!/usr/bin/env bats
# Boundary tests for the build_scripts/lib/ modules behind the lib.sh facade.
#
# #2412 splits the shared build library into domain modules. lib.sh stays the
# one file that build scripts source, so every module must be sourced by it,
# and a function that has moved into a module must not come back into lib.sh.
# A second definition in lib.sh would silently win or lose depending on the
# order of the source lines, so the two copies could drift apart.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
LIB="${REPO_ROOT}/build_scripts/lib.sh"
MODULE_DIR="${REPO_ROOT}/build_scripts/lib"

_module_functions() {
  grep -oE '^[A-Za-z_][A-Za-z0-9_]*\(\)' "$1" | tr -d '()'
}

@test "every lib/ module is sourced by the lib.sh facade" {
  local module name missing=()
  for module in "${MODULE_DIR}"/*.sh; do
    name="$(basename "$module")"
    grep -qE "^source .*/lib/${name}\"\$" "$LIB" || missing+=("$name")
  done
  if ((${#missing[@]})); then
    echo "lib.sh does not source: ${missing[*]}"
    return 1
  fi
}

@test "no function is defined both in lib.sh and in a lib/ module" {
  local module fn dupes=()
  for module in "${MODULE_DIR}"/*.sh; do
    while read -r fn; do
      [[ -n "$fn" ]] || continue
      if grep -qE "^${fn}\(\)" "$LIB"; then
        dupes+=("${fn} ($(basename "$module"))")
      fi
    done < <(_module_functions "$module")
  done
  if ((${#dupes[@]})); then
    printf 'defined in lib.sh and in a module: %s\n' "${dupes[@]}"
    return 1
  fi
}

@test "reporting module owns warn_on_fail, lint_image and emit_packages_manifest" {
  local fn
  for fn in warn_on_fail lint_image emit_packages_manifest; do
    grep -qE "^${fn}\(\)" "${MODULE_DIR}/reporting.sh"
  done
}

@test "lib/ modules run no commands when they are sourced" {
  # Each module may only define functions and comments at top level. Source
  # one in a clean shell with an empty PATH: any top-level command fails.
  local module
  for module in "${MODULE_DIR}"/*.sh; do
    run env -i /bin/bash -c 'PATH=/nonexistent; set -e; source "$1"' _ "$module"
    if [[ "$status" -ne 0 || -n "$output" ]]; then
      echo "$(basename "$module") has source-time side effects: $output"
      return 1
    fi
  done
}
