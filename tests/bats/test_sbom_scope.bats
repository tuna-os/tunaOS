#!/usr/bin/env bats
# SBOM generation must describe the final image, and must not be able to take
# the variant down with it.
#
# This file used to assert the opposite -- "SBOM is blocking" -- and that was
# a deliberate contract, not an accident. It changed because the contract was
# wrong in a way only production showed: `Generate SBOM` runs AFTER the image
# is built, pushed and immutable in GHCR, but sits BEFORE `Create Job
# Outputs`, which writes the digest artifact `Manifest` fans in on. So a dead
# scan skipped the digest artifact, `Manifest` failed at `Load Outputs`, and
# Sign, Gate, Promote and every stage-2 flavor were skipped behind it -- a
# 0/N night for an artifact that is not a promotion precondition
# (2026-08-16 nightly, guppy run 31921372675; tunaOS#1567, #1784).
#
# "Fail closed" still holds where it belongs: an image signature gates
# promotion (see "promotion requires the signing gate" below). An SBOM does
# not. Same line drawn for SBOM attestation in #1560/#1766.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
SBOM_ACTION="${REPO_ROOT}/.github/actions/generate-sbom-spdx/action.yml"
SBOM_SCRIPT="${REPO_ROOT}/scripts/generate-sbom.sh"
# SBOM attestation lives in its own `workflow_run` workflow since #2282, so a
# transparency-log outage gets its own run conclusion and cannot turn a
# nightly that built everything red.
ATTEST_WORKFLOW="${REPO_ROOT}/.github/workflows/attest-sbom.yml"

@test "SBOM scans the squashed image view" {
  run grep -E -- '--scope squashed' "$SBOM_SCRIPT"
  [ "$status" -eq 0 ]
  run grep -E -- '--scope all-layers' "$SBOM_SCRIPT"
  [ "$status" -ne 0 ]
}

@test "SBOM output is still validated, not merely produced" {
  # Both the Syft and fallback producers reject empty or non-SPDX output.
  grep -q 'length > 0' "$SBOM_SCRIPT"
  grep -q 'startswith("SPDX-")' "$SBOM_SCRIPT"
  grep -q 'if-no-files-found: error' "$SBOM_ACTION"
}

@test "a failed SBOM scan costs the SBOM, not the variant" {
  run grep -c 'continue-on-error: true' "$SBOM_ACTION"
  [ "$status" -eq 0 ]
  [ "$output" -ge 3 ]

  # The upload runs only when one producer actually succeeded.
  grep -q "steps.sbom.outcome == 'success'" "$SBOM_ACTION"
}

@test "the scan is bounded by memory as well as by time" {
  # The shell wall clock covers a slow scan; the cgroup keeps a hungry scan
  # from killing the runner agent.
  grep -q 'timeout --kill-after' "$SBOM_SCRIPT"
  grep -q 'systemd-run' "$SBOM_SCRIPT"
  grep -q 'MemoryMax' "$SBOM_SCRIPT"
  grep -q 'MemorySwapMax=0' "$SBOM_SCRIPT"
}

@test "published images use keyless signing and signed SPDX attestations" {
  grep -q 'id-token: write' "$WORKFLOW"
  grep -q 'cosign sign "$index_ref"' "$WORKFLOW"
  # Attestation is a separate run, but it is still keyless and still verified.
  grep -q 'id-token: write' "$ATTEST_WORKFLOW"
  grep -q 'cosign attest --type spdxjson' "$ATTEST_WORKFLOW"
  grep -q 'cosign verify-attestation' "$ATTEST_WORKFLOW"
  run grep -E 'COSIGN_PRIVATE_KEY|SIGNING_SECRET' "$WORKFLOW" "$ATTEST_WORKFLOW"
  [ "$status" -ne 0 ]
}

@test "attestation cannot decide the build run's conclusion" {
  # `continue-on-error: true` was the old answer and it was not enough: it
  # keeps a job from failing the run it is DEFINED in, and the caller's
  # `uses:` job still reports the called workflow's aggregate result. Run
  # 33591594151 concluded failure with 27 of 30 jobs green (#2282).
  # Anchored past any `#`, so the incident write-ups that quote the command
  # in a comment do not read as the command itself.
  run grep -E '^[^#]*cosign attest' "$WORKFLOW"
  [ "$status" -ne 0 ]
  grep -q '^  workflow_run:' "$ATTEST_WORKFLOW"
}

@test "active workflows no longer pass a signing key secret" {
  run grep -R -E 'COSIGN_PRIVATE_KEY|SIGNING_SECRET' \
    "${REPO_ROOT}/.github/workflows" \
    --exclude-dir=archive
  [ "$status" -ne 0 ]
}

@test "promotion requires the signing gate" {
  # Asserted as membership, not as a byte-exact `needs:` line. The literal
  # `[manifest, sign, verify_boot, verify_asahi]` broke the moment
  # verify_desktop joined the gate (#2269) -- a test that fails when the gate
  # gets STRICTER is a test that argues against its own contract. What must
  # hold is that Promote waits on the signature and cannot start without it.
  needs=$(awk '/^  tag-image:/ {f=1} f && /^    needs: \[/ {print; exit}' "$WORKFLOW")
  [ -n "$needs" ]
  for job in manifest sign verify_boot verify_asahi; do
    echo "$needs" | grep -q "\b${job}\b" || {
      echo "Promote no longer needs ${job}: ${needs}" >&2
      return 1
    }
  done
  # Scoped to the Promote job's own `if:`. A file-wide grep passed here even
  # with Promote's guard deleted, because another job carries the same
  # expression on line 1171 -- so the old assertion could not have caught the
  # failure it was written to catch.
  guard=$(awk '/^  tag-image:/ {f=1} f && /^    runs-on:/ {exit} f' "$WORKFLOW")
  echo "$guard" | grep -q "needs.sign.result == 'success'" || {
    echo "Promote's own if: no longer requires a successful sign" >&2
    return 1
  }
}
