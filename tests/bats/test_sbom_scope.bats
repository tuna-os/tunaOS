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

@test "SBOM scans the squashed image view" {
  run grep -E -- '--scope squashed' "$WORKFLOW"
  [ "$status" -eq 0 ]
  run grep -E -- '--scope all-layers' "$WORKFLOW"
  [ "$status" -ne 0 ]
}

@test "SBOM output is still validated, not merely produced" {
  # Unchanged by the blocking/non-blocking switch: a scan that returns
  # something useless must still fail. An empty package list is the shape a
  # silently-degraded scan takes.
  grep -q 'length > 0' "$WORKFLOW"
  grep -q 'startswith("SPDX-")' "$WORKFLOW"
  grep -q 'if-no-files-found: error' "$WORKFLOW"
}

@test "a failed SBOM scan costs the SBOM, not the variant" {
  # The inverse of this file's original assertion -- see the header.
  run bash -c "sed -n '/- name: Generate SBOM/,/- name: Upload SBOM/p' '$WORKFLOW' | grep -c 'continue-on-error: true'"
  [ "$status" -eq 0 ]

  # ...and the soft failure must not be converted straight back into a hard
  # one. `Upload SBOM` carries `if-no-files-found: error`, so with the job
  # left green by continue-on-error it would otherwise run against a file
  # that was never written.
  grep -q "steps.sbom.outcome == 'success'" "$WORKFLOW"
}

@test "the scan is bounded by memory as well as by time" {
  # Two bounds, two different faults. `timeout-minutes` is enforced by the
  # runner agent and so cannot fire when the agent is the casualty (#1567:
  # the step overran its 20-minute limit by 51 minutes and uploaded no logs).
  # The wall clock added by #1572 catches a scan that is slow -- but on the
  # 2026-08-16 nightly the runner died at 7m56s, inside it, because the scan
  # was hungry rather than slow. GOMEMLIMIT is advisory; only a cgroup cap
  # makes the kernel kill syft instead of the agent.
  grep -q '^        timeout-minutes: 20$' "$WORKFLOW"
  grep -q 'timeout --kill-after' "$WORKFLOW"
  grep -q 'systemd-run' "$WORKFLOW"
  grep -q 'MemoryMax' "$WORKFLOW"
  grep -q 'MemorySwapMax=0' "$WORKFLOW"
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
  # Assert `sign` is among Promote's gates rather than pinning the exact gate
  # list: the list grows as deep E2E axes land (verify_desktop, #2263), and
  # scripts/check-ci-contract.py already enforces that Promote covers every
  # blocking gate in the workflow. What this file owns is the signing gate.
  local promote_needs
  promote_needs="$(awk '/^  tag-image:/{f=1} f && /^    needs:/{print; exit}' "$WORKFLOW")"
  [ -n "$promote_needs" ]
  [[ "$promote_needs" == *"sign"* ]]
  grep -q "needs.sign.result == 'success'" "$WORKFLOW"
}
