# Chainguard collaboration brief

> Outreach draft for maintainer review. This is a proposed conversation, not
> an announcement or a claim of Chainguard endorsement.
>
> Tracking: [tunaos#1339](https://github.com/tuna-os/tunaos/issues/1339)

## The angle

TunaOS is a useful edge case for the container supply-chain story: it takes
OCI images all the way to an end-user desktop and bootable ISO. The project
now signs published images and release media with Sigstore's keyless GitHub
Actions identity, verifies the signatures before promotion, and publishes
signed SPDX SBOM attestations for platform images.

That gives Chainguard a concrete ecosystem conversation rather than a generic
request for promotion.

> **Correction (maintainer, 2026-08-13)**: an earlier version of this brief
> named [@tulilirockz](https://github.com/tulilirockz) as an existing TunaOS
> contributor and proposed warm path. That's inaccurate — TunaOS's git
> history was inherited from its bluefin-lts fork point, and all of
> tulilirockz's commits predate that fork (last commit 2025-05-07, over a
> year before TunaOS existed as a separate project). They maintained
> bluefin-lts, not TunaOS. There is no confirmed existing relationship to use
> as a warm path here — this brief should be treated as cold outreach unless
> a maintainer identifies a real contact.

## Evidence maintainers can point to

| Capability | Repository evidence | User-facing evidence |
|---|---|---|
| Keyless image signatures | `reusable-build-image.yml` grants `id-token: write`, signs the immutable index and platform digests, then verifies them | [`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md) |
| Signed SBOMs | The same workflow generates SPDX SBOMs, attaches them with `cosign attest`, and fails closed when required attestations are missing | `cosign verify-attestation` example in [`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md) |
| ISO verification | The artifact workflow emits a checksum and Cosign v3 bundle only after the QEMU boot gate passes | ISO verification instructions in [`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md) |
| Narrow trust boundary | Verification pins the repository, protected `main` workflow identity, and GitHub Actions OIDC issuer | Trust-boundary section in [`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md) |
| Reproducibility hygiene | Third-party Actions are pinned to commit SHAs and source policy is documented | [`PACKAGE-SOURCING.md`](../PACKAGE-SOURCING.md) |

The conversation should describe the current scope accurately: the Q4
milestone is landed for published images and ISOs, while parity for every
release flavor and package artifacts remains tracked work. Do not say that
every TunaOS artifact is already signed or attested.

## Proposed collaboration

Start with a low-commitment technical conversation and let Chainguard choose
the format:

1. Ask whether the Chainguard content or developer-relations team would be
   interested in a short case study or guest post about securing a bootc
   desktop pipeline.
2. Offer a reproducible walkthrough using a public TunaOS image: resolve its
   digest, verify the GitHub Actions certificate identity, inspect the SPDX
   predicate, and explain why the ISO has a separate verification bundle.
3. If there is interest, co-review the boundaries and terminology before
   publication. In particular, distinguish image signatures, SBOM
   attestations, ISO signatures, and provenance; they are related but not
   interchangeable claims.

Possible working title: **“From OCI image to bootable desktop: keyless
signing and SBOM verification in a bootc pipeline.”**

## Draft cold-outreach note

> Hi! We’ve just landed keyless Cosign signing and signed SPDX attestations
> for TunaOS’s published container images, plus verification bundles for the
> bootable ISOs. Since TunaOS carries the OCI supply-chain model through to a
> desktop and boot gate, we thought it might make a useful practical example
> for Chainguard’s supply-chain audience. Would a short technical case study
> or guest post be interesting? We can provide the public workflow, exact
> verification commands, and the remaining gaps rather than presenting this
> as a finished-everything story.

## Guardrails and next steps

- Maintainer approval is required before sending the note or using
  Chainguard's name in promotional copy.
- Do not add Chainguard to [`ADOPTERS.md`](../ADOPTERS.md) unless Chainguard
  confirms an actual development, evaluation, or production relationship.
- Do not disclose private contact details, internal conversations, or
  employment information beyond what the recipient chooses to share.
- Before external publication, re-run the verification examples against a
  current digest and update the remaining-scope sentence from
  [`ROADMAP.md`](../ROADMAP.md).
- Record the outreach date, response, and any agreed deliverable in issue
  #1339; link the resulting post or case study there.
