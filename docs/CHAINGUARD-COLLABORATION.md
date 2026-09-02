# Chainguard Supply-Chain Security Collaboration Angle

> Status: **draft** — collaboration proposal for maintainer review.
> Tracking issue: [#1339](https://github.com/tuna-os/tunaOS/issues/1339) (Chainguard supply-chain collaboration angle).
> Target: Chainguard Open Source & Supply Chain Security Relations / Community Discussions.
> Prepared: 2026-08-29.

---

## Executive Summary

Software supply-chain integrity is central to the design of modern immutable operating systems. **Chainguard** is a recognized leader in secure software supply chains, zero-CVE minimal container base images (Wolfi / Chainguard Images), and keyless cryptographic signing (Sigstore).

**TunaOS** builds container-native, bootable desktop operating systems using `bootc`. We already incorporate Chainguard tooling and base containers—notably `cgr.dev/chainguard/wolfi-base`—across our build pipeline and SBOM extraction workflows.

This document outlines the shared technical alignment, existing usage, and collaborative angles between TunaOS and Chainguard for container-native host security.

---

## Technical Alignment & Existing Touchpoints

### 1. Hardened Builder Images (`wolfi-base`)
- TunaOS utilizes `cgr.dev/chainguard/wolfi-base` as the minimal, hardened base image for auxiliary build tools, SBOM generation scripts, and CI validation containers.
- Renovate automation keeps Wolfi base image digests strictly pinned and refreshed continuously, ensuring zero-CVE builder environments.

### 2. Sigstore & Keyless Verification Architecture
- TunaOS signs all published container images on GHCR and native repository artifacts using Sigstore/cosign keyless workflows.
- Verification is anchored to the public Rekor transparency log, eliminating long-lived static private keys and reducing credential exposure risks.

### 3. Comprehensive SBOM Generation & Provenance
- TunaOS generates machine-readable SPDX SBOMs for published image layers and packages.
- Attestations are attached directly to OCI artifacts, aligning with SLSA Level 3 supply-chain standards.

---

## Proposed Collaboration Vectors

### Vector A: Minimal & Hardened Build Stage Optimization
- **Initiative**: Evaluate expanding Chainguard minimal images across intermediate packaging stages and Tacklebox ISO creation pipelines.
- **Benefit**: Minimize CVE surface area in the desktop OS generation toolchain from source package extraction to ISO publishing.

### Vector B: Joint Case Study / Blog Post on Host OS Supply Chains
- **Topic**: *Securing the Desktop from Base Container to Bare Metal with Wolfi, Sigstore, and bootc*.
- **Content**: A deep dive demonstrating how enterprise desktop Linux distributions can eliminate package-level vulnerability drift and verify cryptographic provenance at boot time.

### Vector C: Supply Chain Attestation Standards for bootc
- **Initiative**: Collaborate on establishing open best practices for embedding and verifying in-toto / cosign attestations within `bootc` bootable host containers during kernel and initramfs boot stages.

---

## Outreach Pitch Template

**Subject**: Collaboration on secure bootable desktop OS supply chains (TunaOS & Chainguard)

> Hi Chainguard Team,
>
> We are the maintainers of **TunaOS** (https://github.com/tuna-os/tunaOS), an open-source, container-native desktop operating system built on `bootc` and Enterprise Linux bases.
>
> In our build and release pipeline, we rely on Chainguard's `wolfi-base` images and Sigstore keyless signing to enforce strict software supply-chain integrity and zero-CVE build stages.
>
> We would love to explore a joint collaboration or technical case study highlighting how Chainguard's minimal base image philosophy and Sigstore provenance extend to bootable, container-native host systems.
>
> Key points of interest:
> 1. Hardening immutable OS builder pipelines with Wolfi images.
> 2. End-to-end provenance verification from OCI container registries down to bare-metal bootc systems.
>
> Please let us know if you'd be open to a brief chat or async discussion on GitHub.
>
> Best regards,
> The TunaOS Team

---

## Outreach Honesty & Protocol Note

- **Cold Outreach Discipline**: As documented in issue #1339 and commit history corrections, prior pre-fork commits from external contributors are bluefin-lts legacy history and do not constitute an existing partnership. This proposal represents cold outreach initiated transparently by TunaOS maintainers.
- **Maintainer Approval Required**: Sending this collaboration pitch to Chainguard channels requires explicit maintainer approval.

---

## Action Checklist

- [ ] Maintainer review and sign-off on collaboration brief
- [ ] Review builder stages for additional Wolfi / Chainguard image adoption opportunities
- [ ] Initiate outreach via public GitHub Discussions / community channels
- [ ] Track contact progress in [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md)
