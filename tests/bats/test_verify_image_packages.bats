#!/usr/bin/env bats
# The package verifier must read both historical list-shaped Gentoo manifests
# and the metadata mapping used by pinned repository-qualified atoms.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

setup() {
  repo="${BATS_TEST_TMPDIR}/repo"
  mkdir -p "${repo}/bin" "${repo}/manifests/desktops" "${repo}/scripts"
  cp "${REPO_ROOT}/scripts/verify-image-packages.sh" "${repo}/scripts/"

  cat >"${repo}/bin/podman" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >>"${PODMAN_LOG}"
printf '\n' >>"${PODMAN_LOG}"
joined="$*"
if [[ "${joined}" == *"/etc/os-release"* ]]; then
  printf 'gentoo\n'
  exit 0
fi
if [[ "${joined}" == *"portageq match"* ]]; then
  [[ "${joined}" == *"grep -q ."* ]]
  exit 0
fi
exit 0
EOF
  chmod +x "${repo}/bin/podman"
  export PATH="${repo}/bin:${PATH}"
  export PODMAN_LOG="${repo}/podman.log"
}

run_verifier() {
  run env PODMAN_LOG="${PODMAN_LOG}" bash "${repo}/scripts/verify-image-packages.sh" fake-image "$1"
}

@test "mapping-shaped Gentoo manifest passes repository-qualified exact atom" {
  cat >"${repo}/manifests/desktops/tuna.yaml" <<'EOF'
packages:
  emerge:
    display_manager: greetd
    source_repositories:
      - name: guru
    packages:
      - =gui-wm/tuna-desktop-1.0.0_beta1::tunaos
EOF

  run_verifier tuna
  [ "$status" -eq 0 ]
  grep -Fq -- '=gui-wm/tuna-desktop-1.0.0_beta1::tunaos' "$PODMAN_LOG"
}
@test "list-shaped Gentoo manifest remains supported" {
  cat >"${repo}/manifests/desktops/legacy.yaml" <<'EOF'
packages:
  emerge:
    - app-editors/vim
EOF

  run_verifier legacy
  [ "$status" -eq 0 ]
  grep -Fq -- 'app-editors/vim' "$PODMAN_LOG"
}

teardown() {
  rm -rf "${repo}"
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
  cat >"${repo}/bin/podman" <<'MOCK'
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
  chmod +x "${repo}/bin/podman"

  # We use the real GNOME manifest which contains "gdm" for el10
  run bash "${BATS_TEST_DIRNAME}/../../scripts/verify-image-packages.sh" "localhost/yellowfin-gnome:base" "gnome"
  # Since podman fails on other packages in gnome.yaml, it should fail but check them via rpm
  [[ "$output" == *"Detected OS inside image: almalinux"* ]]
  [[ "$output" == *"✓ gdm"* ]]
}

@test "verify-packages: Debian GNOME requires bound receipt and native package state" {
  export VARIANT=flounder PLATFORM=linux/amd64
  export CONTRACT_FIXTURE="${repo}/contract.json"
  python3 "${BATS_TEST_DIRNAME}/../../scripts/config.py" generate-debian-contract \
    --variant "$VARIANT" --desktop gnome --platform "$PLATFORM" > "${repo}/contract-path"
  cp "$(cat "${repo}/contract-path")" "$CONTRACT_FIXTURE"
  cat >"${repo}/bin/podman" <<'MOCK'
#!/usr/bin/env bash
if [[ "$*" == *"os-release"* ]]; then
  echo debian
elif [[ "$*" == *"desktop-package-contract.json"* ]]; then
  cat "$CONTRACT_FIXTURE"
elif [[ "$*" == *"dpkg-query"* ]]; then
  echo installed
else
  exit 1
fi
MOCK
  chmod +x "${repo}/bin/podman"
  run bash "${BATS_TEST_DIRNAME}/../../scripts/verify-image-packages.sh" "localhost/debian-gnome:base" gnome
  [ "$status" -eq 0 ]
  [[ "$output" == *"source/cell receipt matches"* ]]
}

@test "verify-packages: routes to /var/db/pkg check for Gentoo" {
  # Mock podman to report gentoo OS and succeed on package checks
  cat >"${repo}/bin/podman" <<'MOCK'
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
  chmod +x "${repo}/bin/podman"

  run bash "${BATS_TEST_DIRNAME}/../../scripts/verify-image-packages.sh" "localhost/guppy-gnome:base" "gnome"
  [[ "$output" == *"Detected OS inside image: gentoo"* ]]
  [[ "$output" == *"✓ gnome-base/gnome-light"* ]]
}
