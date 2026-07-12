#!/usr/bin/env bats
# tests/bats/test_verify_image_packages.bats
# Unit tests for scripts/verify-image-packages.sh

setup() {
  TEST_ROOT="${BATS_TEST_DIRNAME}/test_root_tmp"
  mkdir -p "${TEST_ROOT}"
  export PATH="${TEST_ROOT}/bin:${PATH}"

  # Set up directories
  mkdir -p "${TEST_ROOT}/bin"
  mkdir -p "${TEST_ROOT}/manifests/desktops"

  # Create a mock manifest
  cat >"${TEST_ROOT}/manifests/desktops/testflavor.yaml" <<'YAML'
packages:
  apt:
    - debian-pkg1
    - debian-pkg2
  fedora:
    packages:
      - fedora-pkg1
  el10:
    packages:
      - el-pkg1
  emerge:
    - category/gentoo-pkg1
YAML

  # Stub yq to use the mock manifest path if requested
  # In the real script, it looks at REPO_ROOT/manifests/desktops/flavor.yaml.
  # So we override REPO_ROOT or stub yq to point to our test directory.
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── Argument Validation ───────────────────────────────────────────────────

@test "verify-packages: requires image and flavor arguments" {
  run bash "${BATS_TEST_DIRNAME}/../../scripts/verify-image-packages.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "verify-packages: errors if manifest does not exist" {
  run bash "${BATS_TEST_DIRNAME}/../../scripts/verify-image-packages.sh" "myimage" "nonexistent"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Manifest not found"* ]]
}

# ── OS-specific verification routing ──────────────────────────────────────

@test "verify-packages: routes to RPM check for Enterprise Linux" {
  # Mock podman to report almalinux OS and succeed on package checks
  cat >"${TEST_ROOT}/bin/podman" <<'MOCK'
#!/usr/bin/env bash
if [[ "$*" == *"os-release"* ]]; then
  echo 'almalinux'
  exit 0
fi
if [[ "$*" == *"rpm"* && "$*" == *"gdm"* ]]; then
  exit 0
fi
if [[ "$*" == *"command -v"* || "$*" == *"systemd/system"* ]]; then
  exit 0
fi
exit 1
MOCK
  chmod +x "${TEST_ROOT}/bin/podman"

  # We use the real GNOME manifest which contains "gdm" for el10
  run bash "${BATS_TEST_DIRNAME}/../../scripts/verify-image-packages.sh" "localhost/yellowfin-gnome:base" "gnome"
  # Since podman fails on other packages in gnome.yaml, it should fail but check them via rpm
  [[ "$output" == *"Detected OS inside image: almalinux"* ]]
  [[ "$output" == *"✓ gdm"* ]]
}

@test "verify-packages: routes to dpkg check for Debian/Ubuntu" {
  # Mock podman to report debian OS and succeed on package checks
  cat >"${TEST_ROOT}/bin/podman" <<'MOCK'
#!/usr/bin/env bash
if [[ "$*" == *"os-release"* ]]; then
  echo 'debian'
  exit 0
fi
if [[ "$*" == *"dpkg-query"* && "$*" == *"ubuntu-desktop-minimal"* ]]; then
  echo "install ok installed"
  exit 0
fi
if [[ "$*" == *"command -v"* || "$*" == *"systemd/system"* ]]; then
  exit 0
fi
exit 1
MOCK
  chmod +x "${TEST_ROOT}/bin/podman"

  run bash "${BATS_TEST_DIRNAME}/../../scripts/verify-image-packages.sh" "localhost/debian-gnome:base" "gnome"
  [[ "$output" == *"Detected OS inside image: debian"* ]]
  [[ "$output" == *"✓ ubuntu-desktop-minimal"* ]]
}

@test "verify-packages: routes to /var/db/pkg check for Gentoo" {
  # Mock podman to report gentoo OS and succeed on package checks
  cat >"${TEST_ROOT}/bin/podman" <<'MOCK'
#!/usr/bin/env bash
if [[ "$*" == *"os-release"* ]]; then
  echo 'gentoo'
  exit 0
fi
if [[ "$*" == *"var/db/pkg"* ]]; then
  exit 0
fi
if [[ "$*" == *"command -v"* || "$*" == *"systemd/system"* ]]; then
  exit 0
fi
exit 1
MOCK
  chmod +x "${TEST_ROOT}/bin/podman"

  run bash "${BATS_TEST_DIRNAME}/../../scripts/verify-image-packages.sh" "localhost/guppy-gnome:base" "gnome"
  [[ "$output" == *"Detected OS inside image: gentoo"* ]]
  [[ "$output" == *"✓ gnome-base/gnome-light"* ]]
}
