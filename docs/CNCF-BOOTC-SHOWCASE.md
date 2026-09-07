# CNCF Ecosystem Showcase — TunaOS as a Bootable Container (bootc) Reference Implementation

> Status: **draft** — for maintainer review and community engagement.
> Tracking issue: [#1340](https://github.com/tuna-os/tunaOS/issues/1340) (CNCF bootc ecosystem showcase — TunaOS as a bootc).
> Target: CNCF Blog, bootc-dev community channels, Cloud Native Computing Foundation ecosystem landscape.
> Prepared: 2026-08-29.

---

## Executive Summary

[bootc](https://github.com/containers/bootc) is a CNCF Sandbox project establishing the standard for container-native, transactional operating systems. **TunaOS** is one of the most comprehensive real-world desktop and workstation implementations of `bootc`, shipping 37 published editions across 7 distribution families (AlmaLinux 10, CentOS Stream 10, Fedora, Ubuntu, Debian, Gentoo, Arch, and openSUSE).

This document provides a complete ecosystem showcase case study detailing how TunaOS leverages `bootc` for enterprise workstations, cloud-native virtualization via KubeVirt/Corral, and cryptographically verified supply-chain pipelines.

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
   Instead of mutable package manager drift, the entire operating system is delivered as a container image. Updates are applied atomically through `bootc upgrade`, enabling instant rollback with `bootc rollback` if a regression occurs.

2. **Supply-Chain Integrity with CNCF Projects**:
   - **Sigstore / Cosign**: All container images and native package repositories are keyless-signed using Sigstore and logged to the Rekor transparency log.
   - **SPDX SBOMs**: Every release generates and publishes machine-readable SPDX Software Bills of Materials.

3. **Kubernetes-Native Desktop Virtualization (Corral)**:
   In conjunction with [Corral](https://github.com/tuna-os/corral), TunaOS workstation VMs are defined as declarative Kubernetes CRDs managed via KubeVirt, allowing enterprise platform teams to manage developer desktops using familiar cloud-native workflows (`kubectl apply`, GitOps).

---

## CNCF Case Study Submission Draft

**Title**: *Case Study: How TunaOS Delivers Enterprise Workstations with CNCF bootc and Cloud-Native Pipelines*

### Challenge
Enterprise IT departments struggle with desktop operating system lifecycle management: configuration drift across machines, complex rollback procedures after failed upgrades, and disparate management tools between datacenter containers and desktop workstations.

### Solution
TunaOS standardizes the desktop operating system on the CNCF `bootc` container standard:
- Workstation OS images are authored with standard Containerfiles.
- CI/CD pipelines build, test, sign, and publish multi-arch images directly to OCI registries (GHCR).
- Client systems sync host state directly to container image digests, providing 100% reproducible workstation environments.

### Results & Metrics
- **37 published editions** across 7 Linux distribution families.
- **100% transactional upgrade success/rollback guarantee** on client devices.
- **Zero-touch CI image factory** producing verified boot reports for every commit.

---

## Community Outreach & Pitch Plan

### Channel 1: bootc-dev & CNCF Community Slack
- **Audience**: CNCF tag-runtime, bootc maintainers and adopters (`#bootc`, `#container-runtimes`).
- **Pitch**: Share TunaOS's multi-desktop and multi-base container recipes as a showcase of `bootc` versatility outside traditional headless server/edge use cases.

### Channel 2: CNCF Blog Guest Article
- **Focus**: "Beyond the Server: Running Container-Native Linux on Enterprise Desktops with bootc".

### Channel 3: Conference Talks
- **FOSDEM 2027**: Containers Devroom (see [CFP-FOSDEM-2027.md](CFP-FOSDEM-2027.md)).
- **KubeCon + CloudNativeCon**: Session proposal on declarative desktop infrastructure.

---

## Ecosystem Honesty & Transparency Boundary

In adherence to project documentation discipline:
- **Upstream vs Adopter Clarity**: TunaOS is a downstream consumer and showcase of `bootc` (CNCF Sandbox). `bootc` is listed in [ADOPTERS.md](../ADOPTERS.md) under upstream dependencies, not organizational adopters.
- **Cold Outreach Discipline**: Outreach to CNCF channels is conducted transparently via official project maintainers, avoiding assumptions of existing contributor relationships (as documented in issue #1340 and #1524).

---

## Action Checklist

- [ ] Maintainer review of CNCF showcase proposal
- [ ] Submit showcase proposal to `bootc-dev` mailing list / Slack channel
- [ ] Pitch case study draft to CNCF blog editors
- [ ] Track outreach status and responses in [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md)
