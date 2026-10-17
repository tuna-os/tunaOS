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
fi
if [[ "${joined}" == *"portageq match"* ]]; then
  [[ "${joined}" == *"grep -q ."* ]]
fi
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
