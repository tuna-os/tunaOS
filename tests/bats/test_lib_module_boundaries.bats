#!/usr/bin/env bats
# Boundary contracts for build_scripts/lib/ behind the lib.sh facade.
#
# Build stages keep one source path for compatibility, but domain functions
# live in separate modules. These checks prevent a second definition from
# silently returning to the facade and keep modules safe to source directly.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
LIB="${REPO_ROOT}/build_scripts/lib.sh"
MODULE_DIR="${REPO_ROOT}/build_scripts/lib"

_module_functions() {
  grep -oE '^[A-Za-z_][A-Za-z0-9_]*\(\)' "$1" | tr -d '()'
}

@test "every lib module is sourced by the compatibility facade" {
  local module name missing=()
  for module in "${MODULE_DIR}"/*.sh; do
    name="$(basename "$module")"
    grep -qE "^[[:space:]]*source .*${name//./\\.}\"$" "$LIB" || missing+=("$name")
  done
  if ((${#missing[@]})); then
    echo "lib.sh does not source: ${missing[*]}"
    return 1
  fi
}

@test "no function is defined both in lib.sh and a domain module" {
  local module fn dupes=()
  for module in "${MODULE_DIR}"/*.sh; do
    while read -r fn; do
      [[ -n "$fn" ]] || continue
      if grep -qE "^[[:space:]]*${fn}\(\)" "$LIB"; then
        dupes+=("${fn} ($(basename "$module"))")
      fi
    done < <(_module_functions "$module")
  done
  if ((${#dupes[@]})); then
    printf 'defined in lib.sh and a module: %s\n' "${dupes[*]}"
    return 1
  fi
}

@test "each domain has an owning module" {
  grep -q '^initialize_platform()' "${MODULE_DIR}/platform.sh"
  grep -q '^pkg_install()' "${MODULE_DIR}/packages.sh"
  grep -q '^safe_enable()' "${MODULE_DIR}/service-policy.sh"
  grep -q '^warn_on_fail()' "${MODULE_DIR}/reporting.sh"
  grep -q '^run_buildscripts_for()' "${MODULE_DIR}/orchestration.sh"
}

@test "the facade calls the explicit platform initializer" {
  grep -q '^initialize_platform$' "$LIB"
  grep -q '^initialize_platform()' "${MODULE_DIR}/platform.sh"
}

@test "lib modules have no source-time command side effects" {
  local module
  for module in "${MODULE_DIR}"/*.sh; do
    run env -i /bin/bash -c 'PATH=/nonexistent; set -e; source "$1"' _ "$module"
    if [[ "$status" -ne 0 || -n "$output" ]]; then
      echo "$(basename "$module") has source-time side effects: $output"
      return 1
    fi
  done
}
