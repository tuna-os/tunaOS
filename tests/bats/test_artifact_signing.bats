#!/usr/bin/env bats
# Release ISOs must be checksummed and keylessly signed after boot verification
# and before either publication backend runs.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/reusable-build-artifacts.yml"
PUBLISH_WORKFLOW="${REPO_ROOT}/.github/workflows/publish-isos.yml"
UPLOADER="${REPO_ROOT}/scripts/publish-iso-r2.sh"

@test "ISO signing uses GitHub OIDC without a private key" {
  grep -q 'cosign sign-blob --bundle' "$WORKFLOW"
  grep -q 'cosign verify-blob' "$WORKFLOW"
  run grep -E 'COSIGN_PRIVATE_KEY|SIGNING_SECRET|COSIGN_PASSWORD' "$WORKFLOW"
  [ "$status" -ne 0 ]
}

@test "ISO boot gate precedes signing and publication" {
  boot=$(grep -n 'name: "Boot gate: verify ISO readiness"' "$WORKFLOW" | cut -d: -f1)
  sign=$(grep -n 'name: Checksum, sign, and verify ISO' "$WORKFLOW" | cut -d: -f1)
  artifact=$(grep -n 'name: Upload signed ISO artifact' "$WORKFLOW" | cut -d: -f1)
  r2=$(grep -n 'name: Upload ISO to Cloudflare R2' "$WORKFLOW" | cut -d: -f1)
  [ "$boot" -lt "$sign" ]
  [ "$sign" -lt "$artifact" ]
  [ "$sign" -lt "$r2" ]
  grep -q 'needs: \[generate-matrix, build-and-publish\]' "$PUBLISH_WORKFLOW"
  grep -q 'name: Download signed ISO' "$PUBLISH_WORKFLOW"
}

@test "both publication backends include checksum and bundle sidecars" {
  grep -q 'scripts/publish-iso-r2.sh' "$WORKFLOW"
  grep -q 'publish_iso_as' "$UPLOADER"
  grep -q '"${object}.sha256"' "$UPLOADER"
  grep -q '"${object}.sigstore.json"' "$UPLOADER"
  grep -q '"${ISO}.sha256" "${ISO}.sigstore.json"' "$PUBLISH_WORKFLOW"
}

@test "R2 uploader rejects a checksum that does not match the ISO bytes" {
  iso="${BATS_TEST_TMPDIR}/fish-20261024.iso"
  printf 'iso bytes\n' >"$iso"
  printf '%064d  %s\n' 0 "${iso##*/}" >"${iso}.sha256"
  printf '{}\n' >"${iso}.sigstore.json"

  run "$UPLOADER" "$iso" fish-latest.iso /does/not/matter.json r2:test

  [ "$status" -ne 0 ]
  [[ "$output" == *"signed checksum does not match ISO bytes"* ]]
}

@test "all reusable artifact callers grant OIDC token access" {
  command -v yq >/dev/null 2>&1 || skip "yq unavailable"
  # Per calling job, not a file-wide count: the image-build jobs grant
  # id-token too, so a count would pass with every artifact caller stripped.
  # A job's own permissions block replaces the workflow-level one.
  local wf job grant callers=0 missing=""
  for wf in "${REPO_ROOT}"/.github/workflows/*.yml; do
    while IFS=$'\t' read -r job grant; do
      [ -n "$job" ] || continue
      callers=$((callers + 1))
      [ "$grant" = "write" ] || missing="${missing} $(basename "$wf"):${job}=${grant}"
    done < <(yq -r '.permissions as $top | .jobs // {} | to_entries[]
      | select(.value.uses == "./.github/workflows/reusable-build-artifacts.yml")
      | [.key, ((.value.permissions // $top // {})["id-token"] // "none")] | @tsv' "$wf")
  done
  echo "callers=${callers} missing:${missing}" >&2
  [ "$callers" -ge 4 ]
  [ -z "$missing" ]
}

@test "scheduled grouped ISOs are also signed with sidecars" {
  grouped="${REPO_ROOT}/.github/workflows/publish-iso-groups.yml"
  grep -q 'cosign sign-blob --bundle' "$grouped"
  grep -q 'cosign verify-blob' "$grouped"
  grep -q 'id-token: write' "$grouped"
  grep -q 'iso.sigstore.json' "$grouped"
}
