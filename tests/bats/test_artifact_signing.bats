#!/usr/bin/env bats
# Release ISOs must be checksummed and keylessly signed after boot verification
# and before either publication backend runs.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/reusable-build-artifacts.yml"

@test "ISO signing uses GitHub OIDC without a private key" {
  grep -q 'cosign sign-blob --bundle' "$WORKFLOW"
  grep -q 'cosign verify-blob' "$WORKFLOW"
  run grep -E 'COSIGN_PRIVATE_KEY|SIGNING_SECRET|COSIGN_PASSWORD' "$WORKFLOW"
  [ "$status" -ne 0 ]
}

@test "ISO boot gate precedes signing and publication" {
  boot=$(grep -n 'name: "Boot gate: verify ISO readiness"' "$WORKFLOW" | cut -d: -f1)
  sign=$(grep -n 'name: Checksum, sign, and verify ISO' "$WORKFLOW" | cut -d: -f1)
  r2=$(grep -n 'name: Upload ISO to Cloudflare R2' "$WORKFLOW" | cut -d: -f1)
  release=$(grep -n 'name: Attach ISO to GitHub Release' "$WORKFLOW" | cut -d: -f1)
  [ "$boot" -lt "$sign" ]
  [ "$sign" -lt "$r2" ]
  [ "$sign" -lt "$release" ]
}

@test "both publication backends include checksum and bundle sidecars" {
  grep -q 'live-isos/${LATEST}.sha256' "$WORKFLOW"
  grep -q 'live-isos/${LATEST}.sigstore.json' "$WORKFLOW"
  grep -q '"${ISO}.sha256" "${ISO}.sigstore.json"' "$WORKFLOW"
}

@test "all reusable artifact callers grant OIDC token access" {
  [ "$(grep -c 'id-token: write' "${REPO_ROOT}/.github/workflows/build-variant.yml")" -eq 3 ]
  grep -q 'id-token: write' "${REPO_ROOT}/.github/workflows/publish-isos.yml"
}

@test "scheduled grouped ISOs are also signed with sidecars" {
  grouped="${REPO_ROOT}/.github/workflows/publish-iso-groups.yml"
  grep -q 'cosign sign-blob --bundle' "$grouped"
  grep -q 'cosign verify-blob' "$grouped"
  grep -q 'id-token: write' "$grouped"
  grep -q 'iso.sigstore.json' "$grouped"
}
