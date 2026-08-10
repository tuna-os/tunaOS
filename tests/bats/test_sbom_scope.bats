#!/usr/bin/env bats
# SBOM generation must describe the final image and fail closed before a
# stable image is signed or promoted.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"

@test "SBOM scans the squashed image view" {
  run grep -E -- '--scope squashed' "$WORKFLOW"
  [ "$status" -eq 0 ]
  run grep -E -- '--scope all-layers' "$WORKFLOW"
  [ "$status" -ne 0 ]
}

@test "SBOM is blocking, validated, and time-bounded" {
  run bash -c "sed -n '/- name: Generate SBOM/,/- name: Upload SBOM/p' '$WORKFLOW' | grep 'continue-on-error'"
  [ "$status" -ne 0 ]
  grep -q '^        timeout-minutes: 20$' "$WORKFLOW"
  grep -q 'if-no-files-found: error' "$WORKFLOW"
  grep -q 'length > 0' "$WORKFLOW"
}

@test "published images use keyless signing and signed SPDX attestations" {
  grep -q 'id-token: write' "$WORKFLOW"
  grep -q 'cosign sign "$index_ref"' "$WORKFLOW"
  grep -q 'cosign attest --type spdxjson' "$WORKFLOW"
  grep -q 'cosign verify-attestation' "$WORKFLOW"
  run grep -E 'COSIGN_PRIVATE_KEY|SIGNING_SECRET' "$WORKFLOW"
  [ "$status" -ne 0 ]
}

@test "active workflows no longer pass a signing key secret" {
  run grep -R -E 'COSIGN_PRIVATE_KEY|SIGNING_SECRET' \
    "${REPO_ROOT}/.github/workflows" \
    --exclude-dir=archive
  [ "$status" -ne 0 ]
}

@test "promotion requires the signing gate" {
  grep -q 'needs: \[manifest, sign, verify_boot, verify_asahi\]' "$WORKFLOW"
  grep -q "needs.sign.result == 'success'" "$WORKFLOW"
}
