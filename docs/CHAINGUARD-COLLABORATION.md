# Chainguard supply-chain collaboration brief

> Outreach draft for maintainer review. This is a proposed conversation, not
> an announcement or a claim of Chainguard endorsement.
>
> Tracking: [tunaos#1339](https://github.com/tuna-os/tunaos/issues/1339)

## The angle

TunaOS is a useful edge case for the container supply-chain story: it takes
OCI images through an end-user desktop and bootable ISO pipeline. Published
images and release media now use Sigstore keyless GitHub Actions identity,
signature verification, and signed SPDX SBOM attestations. The project also
has a public verification guide for images, attestations, and ISO bundles:
[`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md).

That gives Chainguard a concrete technical conversation rather than a generic
request for promotion: how supply-chain controls designed for containers carry
through to a bootc desktop and its release media.

### Corrected premise: this is cold outreach

The original issue described `tulilirockz` as a TunaOS contributor with 313
commits and proposed using an existing relationship. That attribution is not
supported: the commits are inherited from the Bluefin LTS fork point, and the
latest relevant commit predates TunaOS as a separate project. Do not describe
the person as a TunaOS contributor, Chainguard representative, or warm contact
without a maintainer-confirmed relationship. Treat this as cold outreach.

## Evidence maintainers can point to

| Capability | Repository evidence | Public explanation |
|---|---|---|
| Keyless image signatures | The reusable image workflow uses GitHub Actions OIDC, signs the immutable index and platform digests, then verifies them | [`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md) |
| Signed SBOMs | The workflow generates SPDX data, attaches it with `cosign attest`, and fails when required attestations are missing | `cosign verify-attestation` in [`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md) |
| ISO verification | The release workflow emits a checksum and Cosign v3 bundle after the boot gate | ISO verification section in [`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md) |
| Trust boundary | Verification pins the repository, protected `main` workflow identity, and GitHub Actions OIDC issuer | Trust-boundary section in [`docs/VERIFY-ARTIFACTS.md`](VERIFY-ARTIFACTS.md) |
| Source hygiene | Third-party Actions are pinned to commit SHAs and package sourcing policy is documented | [`PACKAGE-SOURCING.md`](../PACKAGE-SOURCING.md) |

Keep the scope precise: keyless signing and SBOM attestations landed for the
published image/ISO paths, while parity for every release flavor and package
artifacts remains tracked work. Do not say that every TunaOS artifact is
already signed or attested.

## Proposed collaboration

Start with a low-commitment technical conversation through a public Chainguard
content or developer-relations channel. Let Chainguard choose the format:

1. Ask whether a short case study, guest post, or technical interview about a
   bootc desktop supply-chain pipeline would fit its audience.
2. Offer a reproducible walkthrough using a public TunaOS image: resolve its
   digest, verify the GitHub Actions certificate identity, inspect the SPDX
   predicate, and explain why an ISO has a separate verification bundle.
3. If there is interest, co-review terminology and boundaries before
   publication. Image signatures, SBOM attestations, ISO signatures, and
   provenance are related but are not interchangeable claims.

Possible working title: **From OCI image to bootable desktop: keyless signing
and SBOM verification in a bootc pipeline.**

## Copy-ready cold-outreach note

> Hi! TunaOS has landed keyless Cosign signing and signed SPDX attestations for
> its published container images, plus verification bundles for bootable ISOs.
> Because TunaOS carries the OCI supply-chain model through to a desktop and
> boot gate, it may make a useful practical example for a supply-chain
> audience. Would a short technical case study or guest post be interesting?
> We can provide the public workflow, exact verification commands, and the
> remaining gaps rather than presenting this as a finished-everything story.

## Guardrails and next steps

- Maintainer approval is required before sending the note or using Chainguard's
  name in promotional copy.
- Use a public Chainguard contact/channel; do not infer an introduction from a
  Git history entry or an employee's identity.
- Do not add Chainguard to [`ADOPTERS.md`](../ADOPTERS.md) unless Chainguard
  confirms an actual development, evaluation, or production relationship.
- Before external publication, rerun the verification examples against a
  current digest and update the remaining-scope sentence from [`ROADMAP.md`](../ROADMAP.md).
- Record the outreach date, response, and agreed deliverable in issue #1339;
  link any resulting post or case study there.
