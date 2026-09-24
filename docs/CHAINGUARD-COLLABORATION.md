# Chainguard Supply-Chain Security Collaboration Angle

> Status: **draft** — collaboration proposal for maintainer review.
> Issue that tracks this work: [#1339](https://github.com/tuna-os/tunaOS/issues/1339) (collaboration with Chainguard on the supply chain).
> Target: Chainguard Relations for Open Source & Supply Chain Security / Community Discussions.
> Prepared: 2026-08-29.

---

## Executive Summary

Software supply-chain integrity is central to the design of modern immutable operating systems. **Chainguard** is a recognized leader in security for the software supply chain. Its work includes minimal base images for containers with zero CVEs (Wolfi / Chainguard Images) and keyless cryptography for signatures (Sigstore).

**TunaOS** builds container-native, bootable desktop operating systems using `bootc`. We already incorporate Chainguard tooling and base containers—notably `cgr.dev/chainguard/wolfi-base`—across our build pipeline and SBOM extraction workflows.

This document outlines the shared technical alignment, existing usage, and collaborative angles between TunaOS and Chainguard for container-native host security.

---

## Technical Alignment & Existing Touchpoints

### 1. Hardened Builder Images (`wolfi-base`)
- TunaOS uses `cgr.dev/chainguard/wolfi-base` as the minimal, hardened base image for auxiliary build tools, SBOM generation scripts, and CI validation containers.
- Jobs in Renovate pin the digests of Wolfi base images, and refresh them continuously. This keeps the builder environments at zero CVEs.

### 2. Sigstore & Keyless Verification Architecture
- TunaOS signs all published container images on GHCR and native repository artifacts using Sigstore/cosign keyless workflows.
- TunaOS anchors verification to the public transparency log of Rekor. This removes static private keys with a long life, and reduces the risks of credential exposure.

### 3. Comprehensive SBOM Generation & Provenance
- TunaOS generates SBOMs in machine-readable SPDX format for published image layers and packages.
- TunaOS attaches attestations to OCI artifacts directly. These attestations align with the supply-chain standards of SLSA Level 3.

---

## Proposed Collaboration Vectors

### Vector A: Minimal & Hardened Build Stage Optimization
- **Initiative**: Evaluate more use of Chainguard minimal images in intermediate stages for packages and in Tacklebox pipelines for ISO creation.
- **Benefit**: Less surface area for CVEs in the toolchain that generates the desktop OS. This applies from extraction of source packages to publication of the ISO.

### Vector B: Joint Case Study / Blog Post on Host OS Supply Chains
- **Topic**: *Security for the Desktop from Base Container to Bare Metal with Wolfi, Sigstore, and bootc*.
- **Content**: A deep dive into enterprise distributions of desktop Linux. It shows how they can remove the drift of vulnerabilities at package level, and verify cryptographic provenance at boot time.

### Vector C: Supply Chain Attestation Standards for bootc
- **Initiative**: Work together to establish open best practices for in-toto / cosign attestations. These attestations go into `bootc` bootable host containers, and verification happens during the boot stages for kernel and initramfs.

---

## Outreach Pitch Template

**Subject**: Collaboration on supply chain security for bootable desktop systems (TunaOS & Chainguard)

```text
Hi Chainguard Team,

We maintain TunaOS (https://github.com/tuna-os/tunaOS), an open-source, container-native desktop OS built on bootc.

Our release pipeline uses Chainguard wolfi-base images and Sigstore keyless signatures.

We want to explore a joint case study on how Wolfi and Sigstore protect bootable systems.

Key topics:
1. Hardened builder pipelines with Wolfi images.
2. Full provenance from OCI registries to bare-metal systems.

Please let us know if you want to discuss this on GitHub.

Best regards,
The TunaOS Team
```

---

## Outreach Honesty & Protocol Note

- **Cold Outreach Discipline**: Issue #1339 and the corrections to the commit history record this point. Prior pre-fork commits from external contributors are bluefin-lts legacy history. They do not constitute an existing partnership. TunaOS maintainers make this proposal as cold outreach, and they do it transparently.
- **Maintainer Approval Required**: A maintainer must give explicit approval before anyone sends this collaboration pitch to Chainguard channels.

---

## Action Checklist

- [ ] Maintainer review and sign-off on collaboration brief
- [ ] Review builder stages for more chances to adopt Wolfi / Chainguard images
- [ ] Start outreach via public GitHub Discussions / community channels
- [ ] Track contact progress in [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md)
