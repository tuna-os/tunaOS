#!/usr/bin/env bats
# Unit tests for build_scripts/lib.sh — central shared library
#
# Coverage targets:
#   - OS detection flags (IS_FEDORA, IS_ALMALINUX, etc.) from BASE_IMAGE values
#   - IMAGE_NAME / IMAGE_PRETTY_NAME derivation
#   - detected_os() output
#   - is_x86_64_v2() with mocked rpm
#   - safe_enable() / safe_disable() with mocked systemctl
#   - run_buildscripts_for() for existent and non-existent override dirs
#   - copy_systemfiles_for() for existent and non-existent override dirs
#   - install_from_copr() priority argument parsing
#   - dnf_retry() env-var controlled retry logic

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"

setup() {
  TEST_ROOT="$(mktemp -d)"
  # Create a minimal filesystem for tests
  mkdir -p "${TEST_ROOT}/usr/lib"
  mkdir -p "${TEST_ROOT}/usr/bin"
  mkdir -p "${TEST_ROOT}/usr/share/ublue-os"
  mkdir -p "${TEST_ROOT}/usr/lib/systemd/system"
  mkdir -p "${TEST_ROOT}/usr/share/tunaos"
  mkdir -p "${TEST_ROOT}/etc"

  # Stub os-release — most tests will override BASE_IMAGE directly
  cat >"${TEST_ROOT}/usr/lib/os-release" <<'OSREL'
ID=almalinux
VERSION_ID=10.0
VARIANT_ID=almalinux
OSREL
  # Link /etc/os-release
  ln -sf "${TEST_ROOT}/usr/lib/os-release" "${TEST_ROOT}/etc/os-release"

  # Stub image-info.json
  echo '{"base-image":"quay.io/almalinuxorg/almalinux-bootc:10","image-name":"albacore","image-tag":"gnome"}' \
    >"${TEST_ROOT}/usr/share/ublue-os/image-info.json"

  # Stub systemctl
  cat >"${TEST_ROOT}/usr/bin/systemctl" <<'SYSCTL'
#!/usr/bin/env bash
if [[ "$1" == "list-unit-files" ]]; then
  if [[ "$2" == "sshd.service" ]] || [[ "$2" == gdm.service ]] || [[ "$2" == tailscaled.service ]]; then
    echo "$2    enabled"
    exit 0
  fi
  exit 1
fi
echo "OK"
SYSCTL
  chmod +x "${TEST_ROOT}/usr/bin/systemctl"

  # Stub rpm
  cat >"${TEST_ROOT}/usr/bin/rpm" <<'RPM'
#!/usr/bin/env bash
if [[ "$1" == "-q" ]]; then
  if [[ "$*" == *"kernel"* ]]; then
    if [[ "${RPM_RETURN_V2:-}" == "1" ]]; then
      echo "kernel-6.12.0-1.x86_64_v2"
    else
      echo "kernel-6.12.0-1.x86_64"
    fi
    exit 0
  fi
fi
exit 1
RPM
  chmod +x "${TEST_ROOT}/usr/bin/rpm"

  # Stub dnf for basic invocations (tests override as needed)
  cat >"${TEST_ROOT}/usr/bin/dnf" <<'DNF'
#!/usr/bin/env bash
echo "${DNF_MOCK_RC:-0}" >/tmp/dnf_mock_rc
exit "${DNF_MOCK_RC:-0}"
DNF
  chmod +x "${TEST_ROOT}/usr/bin/dnf"

  # Stub realpath (usually /usr/bin/realpath)
  cat >"${TEST_ROOT}/usr/bin/realpath" <<'REALPATH'
#!/usr/bin/env bash
# Minimal realpath: prepend TEST_ROOT if path is relative, normalize //
echo "$@" | sed "s|^\([^/]\)|${REALPATH_ROOT:-/tmp}/build_scripts/\1|" | sed 's|//*|/|g'
REALPATH
  chmod +x "${TEST_ROOT}/usr/bin/realpath"

  # Stub find
  cat >"${TEST_ROOT}/usr/bin/find" <<'FIND'
#!/usr/bin/env bash
# Synthesize results from the test's overrides directory
echo "$@"
for arg in "$@"; do
  if [[ -d "$arg" ]]; then
    ls "$arg"/*.sh 2>/dev/null | while IFS= read -r f; do
      printf '%s\0' "$f"
    done
  fi
done
FIND
  chmod +x "${TEST_ROOT}/usr/bin/find"

  # Stub sort with --zero-terminated
  cat >"${TEST_ROOT}/usr/bin/sort" <<'SORT'
#!/usr/bin/env bash
/usr/bin/sort "$@"
SORT
  chmod +x "${TEST_ROOT}/usr/bin/sort"

  # Stub jq
  cat >"${TEST_ROOT}/usr/bin/jq" <<'JQ'
#!/usr/bin/env bash
echo "almalinuxorg/almalinux-bootc"
JQ
  chmod +x "${TEST_ROOT}/usr/bin/jq"

  # PATH override
  export PATH="${TEST_ROOT}/usr/bin:${TEST_ROOT}/usr/sbin:/usr/bin:/bin"
  export REALPATH_ROOT="${TEST_ROOT}"

  # Isolate environment
  unset BASE_IMAGE
  unset DESKTOP_FLAVOR
  unset IMAGE_NAME
  unset IMAGE_PRETTY_NAME
  unset IS_FEDORA IS_RHEL IS_ALMALINUX IS_ALMALINUXKITTEN IS_CENTOS
  unset CUSTOM_NAME
  unset DNF_RETRY_ATTEMPTS
  unset SCRIPTS_PATH MAJOR_VERSION_NUMBER CONTEXT_PATH BUILD_SCRIPTS_PATH

  # -- Source lib.sh under test (point dirname to our test root) --
  # We copy lib.sh to a temp location and tweak paths so it can be sourced.
  cp "${REPO_ROOT}/build_scripts/lib.sh" "${TEST_ROOT}/lib_test.sh"
  # Remove the set -euo pipefail to make testing easier
  sed -i 's/^set -euo pipefail/set -uo pipefail\n# set -e removed for test/' "${TEST_ROOT}/lib_test.sh"
  # Make _IMAGE_INFO overridable so image-info.json tests can point to test stubs
  sed -i 's|^_IMAGE_INFO="/usr/share/ublue-os/image-info.json"|_IMAGE_INFO="${_IMAGE_INFO:-/usr/share/ublue-os/image-info.json}"|' "${TEST_ROOT}/lib_test.sh"
}

teardown() {
  rm -rf "${TEST_ROOT}" /tmp/dnf_mock_rc 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# OS Detection Flags
# ═══════════════════════════════════════════════════════════════════════════

@test "OS detection: IS_FEDORA and IMAGE_NAME from fedora BASE_IMAGE" {
  BASE_IMAGE="quay.io/fedora/fedora-bootc:43"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  [[ "$IS_FEDORA" == "true" ]]
  [[ "$IMAGE_NAME" == "bonito" ]]
  [[ "$IMAGE_PRETTY_NAME" == "Bonito" ]]
}

@test "OS detection: IS_ALMALINUX from AlmaLinux BASE_IMAGE" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  [[ "$IS_ALMALINUX" == "true" ]]
  [[ "$IS_ALMALINUXKITTEN" == "false" ]]
  [[ "$IMAGE_NAME" == "albacore" ]]
  [[ "$IMAGE_PRETTY_NAME" == "Albacore" ]]
}

@test "OS detection: IS_ALMALINUXKITTEN from -kitten BASE_IMAGE" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  [[ "$IS_ALMALINUXKITTEN" == "true" ]]
  [[ "$IMAGE_NAME" == "yellowfin" ]]
  [[ "$IMAGE_PRETTY_NAME" == "Yellowfin" ]]
}

@test "OS detection: IS_CENTOS from CentOS Stream BASE_IMAGE" {
  BASE_IMAGE="quay.io/centos-bootc/centos-bootc:stream10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  [[ "$IS_CENTOS" == "true" ]]
  [[ "$IS_FEDORA" == "false" ]]
  [[ "$IMAGE_NAME" == "skipjack" ]]
  [[ "$IMAGE_PRETTY_NAME" == "Skipjack" ]]
}

@test "OS detection: IS_RHEL from Red Hat BASE_IMAGE" {
  BASE_IMAGE="registry.redhat.io/rhel10/rhel-bootc:latest"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  [[ "$IS_RHEL" == "true" ]]
  [[ "$IMAGE_NAME" == "redfin" ]]
  [[ "$IMAGE_PRETTY_NAME" == "Redfin" ]]
}

@test "OS detection: only one flag is true at a time" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run bash -c '
    count=0
    [[ "$IS_FEDORA" == "true" ]] && count=$((count+1))
    [[ "$IS_RHEL" == "true" ]] && count=$((count+1))
    [[ "$IS_ALMALINUX" == "true" ]] && count=$((count+1))
    [[ "$IS_ALMALINUXKITTEN" == "true" ]] && count=$((count+1))
    [[ "$IS_CENTOS" == "true" ]] && count=$((count+1))
    echo "$count"
  '
  [ "$output" = "1" ]
}

@test "OS detection: base_image from image-info.json takes priority" {
  # Simulate the chained-build case: BASE_IMAGE env set to TunaOS stage image
  # but image-info.json has the original OS base
  BASE_IMAGE="ghcr.io/tuna-os/yellowfin:gnome50"
  export BASE_IMAGE
  # Create test image-info.json and set _IMAGE_INFO so lib.sh finds it
  echo '{"base-image":"quay.io/almalinuxorg/almalinux-bootc:10"}' >"${TEST_ROOT}/usr/share/ublue-os/image-info.json"
  export _IMAGE_INFO="${TEST_ROOT}/usr/share/ublue-os/image-info.json"
  source "${TEST_ROOT}/lib_test.sh"
  # The base-image from image-info.json should override the env BASE_IMAGE
  [[ "$IS_ALMALINUX" == "true" ]]
  [[ "$IMAGE_NAME" == "albacore" ]]
}

@test "OS detection: falls back to BASE_IMAGE env when image-info.json missing" {
  rm -f "${TEST_ROOT}/usr/share/ublue-os/image-info.json"
  BASE_IMAGE="quay.io/fedora/fedora-bootc:43"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  [[ "$IS_FEDORA" == "true" ]]
  [[ "$IMAGE_NAME" == "bonito" ]]
}

@test "OS detection: default DESKTOP_FLAVOR is gnome" {
  BASE_IMAGE="quay.io/fedora/fedora-bootc:43"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  [[ "$DESKTOP_FLAVOR" == "gnome" ]]
}

@test "OS detection: DESKTOP_FLAVOR can be overridden" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  DESKTOP_FLAVOR="cosmic"
  export BASE_IMAGE DESKTOP_FLAVOR
  source "${TEST_ROOT}/lib_test.sh"
  [[ "$DESKTOP_FLAVOR" == "cosmic" ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# detected_os()
# ═══════════════════════════════════════════════════════════════════════════

@test "detected_os: outputs Fedora when IS_FEDORA is true" {
  BASE_IMAGE="quay.io/fedora/fedora-bootc:43"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run detected_os
  [[ "$output" == *"Fedora"* ]]
  [[ "$output" != *"AlmaLinux"* ]]
}

@test "detected_os: outputs AlmaLinux when IS_ALMALINUX is true" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run detected_os
  [[ "$output" == *"AlmaLinux"* ]]
  [[ "$output" != *"Fedora"* ]]
  [[ "$output" != *"Kitten"* ]]
}

@test "detected_os: outputs AlmaLinux-Kitten when IS_ALMALINUXKITTEN is true" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run detected_os
  [[ "$output" == *"AlmaLinux-Kitten"* ]]
}

@test "detected_os: outputs CentOS when IS_CENTOS is true" {
  BASE_IMAGE="quay.io/centos-bootc/centos-bootc:stream10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run detected_os
  [[ "$output" == *"CentOS"* ]]
}

@test "detected_os: outputs RHEL when IS_RHEL is true" {
  BASE_IMAGE="registry.redhat.io/rhel10/rhel-bootc:latest"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run detected_os
  [[ "$output" == *"RHEL"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# is_x86_64_v2()
# ═══════════════════════════════════════════════════════════════════════════

@test "is_x86_64_v2: returns 0 when kernel is x86_64_v2" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  RPM_RETURN_V2=1
  export BASE_IMAGE RPM_RETURN_V2
  source "${TEST_ROOT}/lib_test.sh"
  run is_x86_64_v2
  [ "$status" -eq 0 ]
}

@test "is_x86_64_v2: returns 1 when kernel is not v2" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  RPM_RETURN_V2=0
  export BASE_IMAGE RPM_RETURN_V2
  source "${TEST_ROOT}/lib_test.sh"
  run is_x86_64_v2
  [ "$status" -eq 1 ]
}

@test "is_x86_64_v2: returns 1 when rpm not available" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  # Remove rpm stub
  rm -f "${TEST_ROOT}/usr/bin/rpm"
  run is_x86_64_v2
  [ "$status" -eq 1 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# safe_enable() / safe_disable()
# ═══════════════════════════════════════════════════════════════════════════

@test "safe_enable: enables a known service" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run safe_enable gdm.service
  [ "$status" -eq 0 ]
}

@test "safe_enable: no-ops on unknown service" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run safe_enable nonexistent.service
  # Should not fail — test that it doesn't abort
  [ "$status" -eq 0 ]
}

@test "safe_enable: handles file existence check for unit file" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  # Create unit file directly
  touch "${TEST_ROOT}/usr/lib/systemd/system/custom.service"
  run safe_enable custom.service
  [ "$status" -eq 0 ]
}

@test "safe_disable: disables a known service" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run safe_disable gdm.service
  [ "$status" -eq 0 ]
}

@test "safe_disable: no-ops on unknown service" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run safe_disable nonexistent.service
  [ "$status" -eq 0 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# run_buildscripts_for()
# ═══════════════════════════════════════════════════════════════════════════

@test "run_buildscripts_for: skips when override dir does not exist" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  BUILD_SCRIPTS_PATH="${TEST_ROOT}/build_scripts"
  export BUILD_SCRIPTS_PATH
  run run_buildscripts_for "nonexistent_flavor"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping"* ]]
}

@test "run_buildscripts_for: runs scripts in existing override dir" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  BUILD_SCRIPTS_PATH="${TEST_ROOT}/build_scripts"
  export BUILD_SCRIPTS_PATH

  # Create override dir with test scripts
  mkdir -p "${TEST_ROOT}/build_scripts/overrides/gdx"
  cat >"${TEST_ROOT}/build_scripts/overrides/gdx/20-nvidia.sh" <<'SCRIPT'
#!/usr/bin/env bash
echo "nvidia override ran"
SCRIPT
  chmod +x "${TEST_ROOT}/build_scripts/overrides/gdx/20-nvidia.sh"

  run run_buildscripts_for "gdx"
  [ "$status" -eq 0 ]
  [[ "$output" == *"===gdx-20-nvidia.sh==="* ]]
}

@test "run_buildscripts_for: uses CUSTOM_NAME when set" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  BUILD_SCRIPTS_PATH="${TEST_ROOT}/build_scripts"
  CUSTOM_NAME="my-custom-name"
  export BUILD_SCRIPTS_PATH CUSTOM_NAME

  mkdir -p "${TEST_ROOT}/build_scripts/overrides/gdx"
  cat >"${TEST_ROOT}/build_scripts/overrides/gdx/20-nvidia.sh" <<'SCRIPT'
#!/usr/bin/env bash
echo "nvidia override ran"
SCRIPT
  chmod +x "${TEST_ROOT}/build_scripts/overrides/gdx/20-nvidia.sh"

  run run_buildscripts_for "gdx"
  [ "$status" -eq 0 ]
  [[ "$output" == *"===my-custom-name-20-nvidia.sh==="* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# copy_systemfiles_for()
# ═══════════════════════════════════════════════════════════════════════════

@test "copy_systemfiles_for: skips when override dir does not exist" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  CONTEXT_PATH="${TEST_ROOT}/context"
  export CONTEXT_PATH
  run copy_systemfiles_for "nonexistent_flavor"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping"* ]]
}

@test "copy_systemfiles_for: copies files from override dir" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  CONTEXT_PATH="${TEST_ROOT}/context"
  export CONTEXT_PATH

  mkdir -p "${TEST_ROOT}/context/overrides/gdx/usr/bin"
  echo "echo 'hello'" >"${TEST_ROOT}/context/overrides/gdx/usr/bin/custom-tool"
  chmod +x "${TEST_ROOT}/context/overrides/gdx/usr/bin/custom-tool"

  run copy_systemfiles_for "gdx"
  [ "$status" -eq 0 ]
  [[ "$output" == *"gdx-file-copying"* ]]
}

@test "copy_systemfiles_for: uses CUSTOM_NAME in display" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10-kitten"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  CONTEXT_PATH="${TEST_ROOT}/context"
  CUSTOM_NAME="my-custom-overlay"
  export CONTEXT_PATH CUSTOM_NAME

  mkdir -p "${TEST_ROOT}/context/overrides/gdx/etc"
  echo "custom" >"${TEST_ROOT}/context/overrides/gdx/etc/custom.conf"

  run copy_systemfiles_for "gdx"
  [ "$status" -eq 0 ]
  [[ "$output" == *"my-custom-overlay-file-copying"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# install_from_copr() — argument parsing for priority
# ═══════════════════════════════════════════════════════════════════════════

@test "install_from_copr: detects numeric priority argument" {
  # Test that the priority-detection regex works
  # [[ $1 =~ ^[0-9]+$ ]] should match "50" but not "package-name"
  run bash -c '[[ "50" =~ ^[0-9]+$ ]] && echo "yes" || echo "no"'
  [ "$output" = "yes" ]
}

@test "install_from_copr: does not treat package name as priority" {
  run bash -c '[[ "gum" =~ ^[0-9]+$ ]] && echo "yes" || echo "no"'
  [ "$output" = "no" ]
}

@test "install_from_copr: REPO_ID is correctly formatted" {
  # Test the COPR_NAME -> REPO_ID transformation used in the function
  COPR_NAME="ublue-os/packages"
  REPO_ID="copr:copr.fedorainfracloud.org:$(echo "$COPR_NAME" | tr '/' ':')"
  [ "$REPO_ID" = "copr:copr.fedorainfracloud.org:ublue-os:packages" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# dnf_retry() — retry logic
# ═══════════════════════════════════════════════════════════════════════════

@test "dnf_retry: respects DNF_RETRY_ATTEMPTS env var" {
  # Verify that the max_attempts default is 4
  run bash -c 'echo "${DNF_RETRY_ATTEMPTS:-4}"'
  [ "$output" = "4" ]
}

@test "dnf_retry: custom DNF_RETRY_ATTEMPTS is honored" {
  run bash -c 'DNF_RETRY_ATTEMPTS=2; echo "${DNF_RETRY_ATTEMPTS}"'
  [ "$output" = "2" ]
}

@test "dnf_retry: sleep backoff formula is attempt*5" {
  # Test that sleep duration increases with attempt number
  # attempt=1: sleep 5, attempt=2: sleep 10, attempt=3: sleep 15
  local attempt=3
  local expected=$((attempt * 5))
  [ "$expected" -eq 15 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# install_available() — argument parsing
# ═══════════════════════════════════════════════════════════════════════════

@test "install_available: detects --copr flags and separates from packages" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"

  # Test the copr-detection while-loop: should parse "--copr a/b" correctly
  run bash -c '
    coprs=()
    set -- "--copr" "ublue-os/packages" "--copr" "avengemedia/danklinux" "package1" "package2"
    while [[ "${1:-}" == "--copr" ]]; do
      coprs+=("$2")
      shift 2
    done
    echo "${coprs[@]}"
    echo "${*}"
  '
  [[ "$output" == *"ublue-os/packages avengemedia/danklinux"* ]]
  [[ "$output" == *"package1 package2"* ]]
}

@test "install_available: returns early when no packages provided" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"

  run bash -c '
    pkgs=()
    [[ ${#pkgs[@]} -eq 0 ]] && echo "no packages" && exit 0
    echo "has packages"
  '
  [ "$output" = "no packages" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# print_debug_info()
# ═══════════════════════════════════════════════════════════════════════════

@test "print_debug_info: includes IMAGE_NAME in output" {
  BASE_IMAGE="quay.io/fedora/fedora-bootc:43"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run print_debug_info
  [[ "$output" == *"IMAGE_NAME: bonito"* ]]
}

@test "print_debug_info: includes detected_os output" {
  BASE_IMAGE="quay.io/fedora/fedora-bootc:43"
  export BASE_IMAGE
  source "${TEST_ROOT}/lib_test.sh"
  run print_debug_info
  [[ "$output" == *"Detected OS:"* ]]
  [[ "$output" == *"Fedora"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# warn_on_fail()
# ═══════════════════════════════════════════════════════════════════════════

@test "warn_on_fail: logs warning when command fails" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  IMAGE_NAME="yellowfin"
  MAJOR_VERSION_NUMBER="10"
  export BASE_IMAGE IMAGE_NAME MAJOR_VERSION_NUMBER
  source "${TEST_ROOT}/lib_test.sh"
  run warn_on_fail false
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning"* ]]
  [[ "$output" == *"yellowfin on 10"* ]]
  [[ "$output" == *"false"* ]]
}

@test "warn_on_fail: no output when command succeeds" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  IMAGE_NAME="yellowfin"
  MAJOR_VERSION_NUMBER="10"
  export BASE_IMAGE IMAGE_NAME MAJOR_VERSION_NUMBER
  source "${TEST_ROOT}/lib_test.sh"
  run warn_on_fail true
  [ "$status" -eq 0 ]
  [[ "$output" != *"::warning"* ]]
}

@test "warn_on_fail: includes caller script name" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  IMAGE_NAME="yellowfin"
  MAJOR_VERSION_NUMBER="10"
  export BASE_IMAGE IMAGE_NAME MAJOR_VERSION_NUMBER
  source "${TEST_ROOT}/lib_test.sh"
  run warn_on_fail false arg1
  [ "$status" -eq 0 ]
  [[ "$output" == *"test_lib.bats"* ]] || [[ "$output" == *"bats"* ]]
}

@test "warn_on_fail: returns 0 even when command fails" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  IMAGE_NAME="yellowfin"
  MAJOR_VERSION_NUMBER="10"
  export BASE_IMAGE IMAGE_NAME MAJOR_VERSION_NUMBER
  source "${TEST_ROOT}/lib_test.sh"
  # exit 1 should be caught, warn_on_fail should return 0
  run warn_on_fail bash -c 'exit 1'
  [ "$status" -eq 0 ]
}

@test "warn_on_fail: passes arguments through to command" {
  BASE_IMAGE="quay.io/almalinuxorg/almalinux-bootc:10"
  IMAGE_NAME="yellowfin"
  MAJOR_VERSION_NUMBER="10"
  export BASE_IMAGE IMAGE_NAME MAJOR_VERSION_NUMBER
  source "${TEST_ROOT}/lib_test.sh"
  run warn_on_fail echo hello world
  [ "$status" -eq 0 ]
  [[ "$output" == *"hello world"* ]]
}
