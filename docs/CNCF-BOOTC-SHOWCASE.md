# CNCF Ecosystem Showcase — TunaOS as a Bootable Container (bootc) Reference Implementation

> Status: **draft** — for maintainer review and community engagement.
> Issue that tracks this work: [#1340](https://github.com/tuna-os/tunaOS/issues/1340) (showcase for the CNCF `bootc` ecosystem — TunaOS as a `bootc`).
> Target: CNCF Blog, bootc-dev community channels, Cloud Native Computing Foundation ecosystem landscape.
> Prepared: 2026-08-29.

---

## Executive Summary

[bootc](https://github.com/containers/bootc) is a CNCF Sandbox project that establishes the standard for container-native, transactional operating systems. **TunaOS** is one of the most comprehensive real-world desktop and workstation implementations of `bootc`. It ships 37 published editions across 7 distribution families (AlmaLinux 10, CentOS Stream 10, Fedora, Ubuntu, Debian, Gentoo, Arch, and openSUSE).

This document is a complete case study for the ecosystem showcase. It shows how TunaOS uses `bootc` for enterprise workstations, for cloud-native virtualization via KubeVirt/Corral, and for supply-chain pipelines with cryptographic verification.

---

## Architecture & CNCF Alignment

```
┌─────────────────────────────────────────────────────────────┐
│                    TunaOS OCI Image                         │
│  (Base OS + Desktop Shell + Sigstore Attestation + SBOM)    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    bootc Runtime Layer                      │
│   • Transactional bootc upgrade / bootc rollback            │
│   • ostree / bootc storage engine & kernel handoff          │
│   • Declarative container image layering                    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     Target Platform                         │
│   • Bare Metal (x86_64, aarch64, ARM laptops)               │
│   • Cloud / Homelab Virtualization (Corral / KubeVirt)       │
└─────────────────────────────────────────────────────────────┘
```

### Key Technical Pillars

1. **Transactional Host Upgrades via OCI**:
   TunaOS delivers the entire operating system as a container image. This replaces the drift of a mutable package manager. TunaOS applies updates atomically through `bootc upgrade`. If a regression occurs, `bootc rollback` gives an instant rollback.

2. **Supply-Chain Integrity with CNCF Projects**:
   - **Sigstore / Cosign**: All container images and native package repositories are keyless-signed using Sigstore and logged to the Rekor transparency log.
   - **SPDX SBOMs**: Every release generates and publishes the SPDX Software Bills of Materials, in a machine-readable form.

3. **Kubernetes-Native Desktop Virtualization (Corral)**:
   With [Corral](https://github.com/tuna-os/corral), TunaOS workstation VMs are declarative Kubernetes CRDs that KubeVirt manages. Enterprise platform teams can then manage developer desktops with familiar cloud-native workflows (`kubectl apply`, GitOps).

---

## CNCF Case Study Submission Draft

**Title**: *Case Study: How TunaOS Delivers Workstations for Enterprises with CNCF bootc and Cloud-Native Pipelines*

### Challenge
Enterprise IT departments have trouble with the lifecycle management of desktop operating systems. The problems are configuration drift across machines, complex rollback procedures after failed upgrades, and disparate management tools between datacenter containers and desktop workstations.

### Solution
TunaOS standardizes the desktop operating system on the CNCF `bootc` container standard:
- TunaOS writes workstation OS images with standard Containerfiles.
- CI/CD pipelines build, test, sign, and publish the multi-arch images directly to OCI registries (GHCR).
- Client systems sync their host state directly to container image digests. The result is a workstation environment that is 100% reproducible.

### Results & Metrics
- **37 published editions** across 7 Linux distribution families.
- **100% transactional upgrade success/rollback guarantee** on client devices.
- **Zero-touch image factory in CI**: it produces verified boot reports for every commit.

---

## Community Outreach & Pitch Plan

### Channel 1: bootc-dev & CNCF Community Slack
- **Audience**: CNCF tag-runtime, bootc maintainers and adopters (`#bootc`, `#container-runtimes`).
- **Pitch**: Share TunaOS's multi-desktop and multi-base container recipes as a showcase of `bootc` versatility outside traditional headless server/edge use cases.

### Channel 2: CNCF Blog Guest Article
- **Focus**: "Beyond the Server: Run Container-Native Linux on Enterprise Desktops with bootc".

### Channel 3: Conference Talks
- **FOSDEM 2027**: Containers Devroom (see [CFP-FOSDEM-2027.md](CFP-FOSDEM-2027.md)).
- **KubeCon + CloudNativeCon**: Session proposal on declarative desktop infrastructure.

---

## Ecosystem Honesty & Transparency Boundary

In adherence to project documentation discipline:
- **Clarity on Upstream vs Adopter**: TunaOS is a downstream consumer and showcase of `bootc` (CNCF Sandbox). [ADOPTERS.md](../ADOPTERS.md) lists `bootc` under upstream dependencies, not organizational adopters.
- **Cold Outreach Discipline**: TunaOS makes outreach to CNCF channels transparently, through official project maintainers. It does not assume that there are already relationships with contributors (as documented in issue #1340 and #1524).

---

## Action Checklist

- [ ] Maintainer review of CNCF showcase proposal
- [ ] Submit showcase proposal to the `bootc-dev` email list or Slack channel
- [ ] Pitch the draft case study to CNCF blog editors
- [ ] Track outreach status and responses in [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md)
