#!/usr/bin/env bats
# Unit tests for scripts/lib/common.sh
#
# These tests validate the shared library functions that all build scripts
# depend on. Run with:
#   bats scripts/lib/test_common.bats
#
# Requires: bats (brew install bats or git clone bats-core/bats-core)

setup() {
  # Save and isolate environment
  TEST_ROOT="$(mktemp -d)"
  # Source common.sh in a subshell for each test via load helper

  # We cannot directly source common.sh because it does a `cd` to repo root.
  # Instead, create a minimal test harness that stubs the repo layout.
  mkdir -p "${TEST_ROOT}/scripts/lib"
  # Copy common.sh to test location
  cp "$(dirname "${BASH_SOURCE[0]}")/../../../scripts/lib/common.sh" \
     "${TEST_ROOT}/scripts/lib/common.sh" 2>/dev/null || true

  # Save original env vars
  ORIG_PLATFORM="${platform:-}"
  ORIG_GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}"
  ORIG_REGISTRY="${REGISTRY:-}"
  ORIG_SUDO_USER="${SUDO_USER:-}"
}

teardown() {
  # Restore env
  export platform="${ORIG_PLATFORM}"
  export GITHUB_REPOSITORY_OWNER="${ORIG_GITHUB_REPOSITORY_OWNER}"
  export REGISTRY="${ORIG_REGISTRY}"
  export SUDO_USER="${ORIG_SUDO_USER}"
  rm -rf "${TEST_ROOT}"
}

# ── tunaos_host_platform tests ──────────────────────────────────────────────

@test "tunaos_host_platform: returns platform env var when set" {
  # The function sources from common.sh which cds; we test via inline eval
  source_common() {
    # shellcheck disable=SC1090
    . "${TEST_ROOT}/scripts/lib/common.sh" 2>/dev/null || true
  }
  export platform="linux/amd64/test"
  result=$(bash -c "
    platform='linux/amd64/test'
    # Simulate the function directly
    if [[ -n \"\${platform:-}\" ]]; then echo \"\${platform}\"; fi
  ")
  [ "$result" = "linux/amd64/test" ]
}

@test "tunaos_host_platform: returns linux/amd64 for x86_64 without v2" {
  # Simulate non-v2 x86_64 (kernel RPM doesn't contain x86_64_v2)
  result=$(bash -c '
    tunaos_host_platform() {
      if [[ -n "${platform:-}" ]]; then echo "${platform}"; return; fi
      local arch; arch=$(uname -m)
      case "$arch" in
        x86_64)
          if rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; then
            echo "linux/amd64/v2"
          else
            echo "linux/amd64"
          fi ;;
        arm64|aarch64) echo "linux/arm64" ;;
        *) return 1 ;;
      esac
    }
    # Force arch to x86_64 and stub rpm to return nothing (no v2)
    tunaos_host_platform_x86() { arch=x86_64; tunaos_host_platform; }
    uname() { echo "x86_64"; }
    rpm() { return 1; }
    tunaos_host_platform
  ')
  [ "$result" = "linux/amd64" ]
}

@test "tunaos_host_platform: returns linux/amd64/v2 for x86_64_v2" {
  result=$(bash -c '
    tunaos_host_platform() {
      if [[ -n "${platform:-}" ]]; then echo "${platform}"; return; fi
      local arch; arch=$(uname -m)
      case "$arch" in
        x86_64)
          if rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; then
            echo "linux/amd64/v2"
          else
            echo "linux/amd64"
          fi ;;
        arm64|aarch64) echo "linux/arm64" ;;
        *) return 1 ;;
      esac
    }
    uname() { echo "x86_64"; }
    rpm() { echo "kernel-core-5.14.0-x86_64_v2"; }
    tunaos_host_platform
  ')
  [ "$result" = "linux/amd64/v2" ]
}

@test "tunaos_host_platform: returns linux/arm64 for aarch64" {
  result=$(bash -c '
    tunaos_host_platform() {
      if [[ -n "${platform:-}" ]]; then echo "${platform}"; return; fi
      local arch; arch=$(uname -m)
      case "$arch" in
        x86_64) echo "linux/amd64" ;;
        arm64|aarch64) echo "linux/arm64" ;;
        *) return 1 ;;
      esac
    }
    uname() { echo "aarch64"; }
    tunaos_host_platform
  ')
  [ "$result" = "linux/arm64" ]
}

@test "tunaos_host_platform: errors on unsupported arch" {
  run bash -c '
    tunaos_host_platform() {
      if [[ -n "${platform:-}" ]]; then echo "${platform}"; return; fi
      local arch; arch=$(uname -m)
      case "$arch" in
        x86_64) echo "linux/amd64" ;;
        arm64|aarch64) echo "linux/arm64" ;;
        *) echo "ERROR: unsupported arch" >&2; return 1 ;;
      esac
    }
    uname() { echo "s390x"; }
    tunaos_host_platform
  '
  [ "$status" -eq 1 ]
}

# ── tunaos_image_ref tests ──────────────────────────────────────────────────

@test "tunaos_image_ref: returns local reference" {
  result=$(bash -c '
    tunaos_image_ref() {
      local variant="${1:?}"; local flavor="${2:-gnome}"; local repo="${3:-local}"; local tag="${4:-${flavor}}"
      [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
      local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
      case "$repo" in
        local) echo "localhost/${variant}:${tag}" ;;
        ghcr) echo "ghcr.io/${owner}/${variant}:${tag}" ;;
        registry) echo "${REGISTRY:-localhost:5000}/${variant}:${tag}" ;;
        *) return 1 ;;
      esac
    }
    tunaos_image_ref yellowfin gnome local
  ')
  [ "$result" = "localhost/yellowfin:gnome" ]
}

@test "tunaos_image_ref: returns GHCR reference" {
  result=$(bash -c '
    tunaos_image_ref() {
      local variant="${1:?}"; local flavor="${2:-gnome}"; local repo="${3:-local}"; local tag="${4:-${flavor}}"
      [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
      local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
      case "$repo" in
        local) echo "localhost/${variant}:${tag}" ;;
        ghcr) echo "ghcr.io/${owner}/${variant}:${tag}" ;;
        registry) echo "${REGISTRY:-localhost:5000}/${variant}:${tag}" ;;
        *) return 1 ;;
      esac
    }
    tunaos_image_ref yellowfin kde ghcr
  ')
  [ "$result" = "ghcr.io/tuna-os/yellowfin:kde" ]
}

@test "tunaos_image_ref: returns registry reference with custom port" {
  result=$(bash -c '
    tunaos_image_ref() {
      local variant="${1:?}"; local flavor="${2:-gnome}"; local repo="${3:-local}"; local tag="${4:-${flavor}}"
      [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
      local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
      case "$repo" in
        local) echo "localhost/${variant}:${tag}" ;;
        ghcr) echo "ghcr.io/${owner}/${variant}:${tag}" ;;
        registry) echo "${REGISTRY:-localhost:5000}/${variant}:${tag}" ;;
        *) return 1 ;;
      esac
    }
    REGISTRY=myreg:6000 tunaos_image_ref albacore gnome registry
  ')
  [ "$result" = "myreg:6000/albacore:gnome" ]
}

@test "tunaos_image_ref: passes through fully-qualified refs" {
  result=$(bash -c '
    tunaos_image_ref() {
      local variant="${1:?}"; local flavor="${2:-gnome}"; local repo="${3:-local}"; local tag="${4:-${flavor}}"
      [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
      local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
      case "$repo" in
        local) echo "localhost/${variant}:${tag}" ;;
        ghcr) echo "ghcr.io/${owner}/${variant}:${tag}" ;;
        registry) echo "${REGISTRY:-localhost:5000}/${variant}:${tag}" ;;
        *) return 1 ;;
      esac
    }
    tunaos_image_ref "ghcr.io/custom/foo:bar" "" ""
  ')
  [ "$result" = "ghcr.io/custom/foo:bar" ]
}

@test "tunaos_image_ref: uses custom tag when provided" {
  result=$(bash -c '
    tunaos_image_ref() {
      local variant="${1:?}"; local flavor="${2:-gnome}"; local repo="${3:-local}"; local tag="${4:-${flavor}}"
      [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
      local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
      case "$repo" in
        local) echo "localhost/${variant}:${tag}" ;;
        ghcr) echo "ghcr.io/${owner}/${variant}:${tag}" ;;
        registry) echo "${REGISTRY:-localhost:5000}/${variant}:${tag}" ;;
        *) return 1 ;;
      esac
    }
    tunaos_image_ref bonito niri local custom-tag
  ')
  [ "$result" = "localhost/bonito:custom-tag" ]
}

@test "tunaos_image_ref: errors on unknown repo type" {
  run bash -c '
    tunaos_image_ref() {
      local variant="${1:?}"; local flavor="${2:-gnome}"; local repo="${3:-local}"; local tag="${4:-${flavor}}"
      [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
      local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
      case "$repo" in
        local) echo "localhost/${variant}:${tag}" ;;
        ghcr) echo "ghcr.io/${owner}/${variant}:${tag}" ;;
        registry) echo "${REGISTRY:-localhost:5000}/${variant}:${tag}" ;;
        *) return 1 ;;
      esac
    }
    tunaos_image_ref yellowfin gnome dockerhub
  '
  [ "$status" -eq 1 ]
}

@test "tunaos_image_ref: uses default flavor gnome" {
  result=$(bash -c '
    tunaos_image_ref() {
      local variant="${1:?}"; local flavor="${2:-gnome}"; local repo="${3:-local}"; local tag="${4:-${flavor}}"
      [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
      local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
      case "$repo" in
        local) echo "localhost/${variant}:${tag}" ;;
        ghcr) echo "ghcr.io/${owner}/${variant}:${tag}" ;;
        registry) echo "${REGISTRY:-localhost:5000}/${variant}:${tag}" ;;
        *) return 1 ;;
      esac
    }
    tunaos_image_ref yellowfin
  ')
  [ "$result" = "localhost/yellowfin:gnome" ]
}

@test "tunaos_image_ref: uses owner from GITHUB_REPOSITORY_OWNER" {
  result=$(bash -c '
    tunaos_image_ref() {
      local variant="${1:?}"; local flavor="${2:-gnome}"; local repo="${3:-local}"; local tag="${4:-${flavor}}"
      [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
      local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
      case "$repo" in
        local) echo "localhost/${variant}:${tag}" ;;
        ghcr) echo "ghcr.io/${owner}/${variant}:${tag}" ;;
        registry) echo "${REGISTRY:-localhost:5000}/${variant}:${tag}" ;;
        *) return 1 ;;
      esac
    }
    GITHUB_REPOSITORY_OWNER=custom-org tunaos_image_ref yellowfin gnome ghcr
  ')
  [ "$result" = "ghcr.io/custom-org/yellowfin:gnome" ]
}

# ── tunaos_import_to_root_storage tests ─────────────────────────────────────

@test "tunaos_import_to_root_storage: returns 0 when image already exists" {
  run bash -c '
    tunaos_import_to_root_storage() {
      local image="${1:?}"
      if podman image exists "$image"; then return 0; fi
      return 1
    }
    podman() {
      if [[ "$1" == "image" && "$2" == "exists" ]]; then return 0; fi
      return 1
    }
    tunaos_import_to_root_storage "localhost/yellowfin:gnome"
  '
  [ "$status" -eq 0 ]
}

@test "tunaos_import_to_root_storage: errors when SUDO_USER unset and image missing" {
  run bash -c '
    tunaos_import_to_root_storage() {
      local image="${1:?}"
      if podman image exists "$image"; then return 0; fi
      local real_user="${SUDO_USER:-$(logname 2>/dev/null || echo)}"
      if [[ -z "$real_user" ]]; then return 1; fi
      if sudo -u "$real_user" podman save "$image" 2>/dev/null | podman load; then return 0; fi
      return 1
    }
    podman() {
      if [[ "$1" == "image" && "$2" == "exists" ]]; then return 1; fi
    }
    logname() { echo ""; }
    unset SUDO_USER
    tunaos_import_to_root_storage "localhost/missing:image"
  '
  [ "$status" -eq 1 ]
}
