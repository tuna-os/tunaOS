# Chainguard collaboration brief

**Status**: outreach proposal — no partnership or endorsement is implied
**Tracker**: [#1339](https://github.com/tuna-os/tunaos/issues/1339)
**Related work**: [#1187](https://github.com/tuna-os/tunaos/issues/1187),
[#1303](https://github.com/tuna-os/tunaos/issues/1303),
[#1305](https://github.com/tuna-os/tunaos/issues/1305)

## Purpose

Give the maintainer and outreach contributors a factual, low-friction starting
point for exploring a Chainguard case study, guest post, or technical exchange.
The first contact should be exploratory: ask whether the story is relevant to
Chainguard, and let the contact choose the appropriate channel and format.

## Verified TunaOS story

These are the claims we can substantiate from the repository today:

- Published OCI images are signed with keyless Sigstore Cosign using the
  protected GitHub Actions workflow identity.
- Each published platform image carries a signed SPDX SBOM attestation.
- Published ISOs carry a checksum and a Cosign verification bundle after the
  QEMU boot gate passes.
- Verification is fail-closed against a specific repository, workflow, main
  branch, and OIDC issuer; signatures from forks or pull-request refs do not
  satisfy the trust policy.
- The public verification commands are documented in
  [`VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md), and the implementation is in
  [`reusable-build-image.yml`](../.github/workflows/reusable-build-image.yml)
  and [`reusable-build-artifacts.yml`](../.github/workflows/reusable-build-artifacts.yml).

Do not describe this as “every release artifact” until release cadence parity
and the remaining artifact scope in #1187 are complete. Say “published images
and ISOs covered by the current workflows” when precision matters.

## Suggested first route

Start with `tulilirockz`, an established TunaOS contributor who is identified
in the issue as a Chainguard engineer. Ask them to sanity-check the angle and,
if appropriate, forward it internally to the relevant Chainguard community or
content contact. Do not use employer affiliation as an endorsement, imply
that they speak for Chainguard, or include private contact information in the
repository.

Suggested note:

> TunaOS now has a public, verifiable supply-chain story around bootc desktop
> images: keyless Cosign signatures, signed SPDX SBOM attestations, and
> post-boot-gate ISO bundles. Would this be interesting as a short technical
> case study or guest post for Chainguard? If so, what channel and scope would
> work best? No expectation either way—we would be happy to share the existing
> verification docs for a technical sanity check.

## If there is interest

Use a small, reviewable collaboration package:

1. A technical walkthrough based on the public workflow and verification docs.
2. One reproducible example verifying an OCI digest and its SPDX attestation.
3. One reproducible example verifying an ISO checksum and Cosign bundle.
4. A short limitations section covering release cadence parity, artifact
   coverage, and the protected-workflow trust boundary.
5. Review by TunaOS maintainers and the collaborator before publication.

The success condition for this tracker is an agreed next conversation or
content scope—not a promised case study. Record any accepted collaboration in
an issue or PR before making public claims about it.
