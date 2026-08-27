# Platform Engineering & DevSecOps Workstation Guide

> Container-native immutable workstation OS architecture for platform engineering teams and enterprise DevSecOps environments.

---

## Overview

TunaOS provides bootc-based, container-native immutable desktop operating system images built on enterprise foundations (Fedora, AlmaLinux, CentOS Stream). For platform engineering and DevSecOps teams, container-native OS architecture offers unprecedented developer environment consistency, cryptographic image verification, zero-drift OS state, and container registry delivery.

## Key Capabilities for Platform Engineering

| Feature | Benefit for DevSecOps | Implementation |
|---|---|---|
| **OCI Registry Distribution** | Ship desktop OS updates via standard container registries (`ghcr.io`, internal OCI registries) | `bootc update` / `bootc switch` |
| **Sigstore / Rekor Attestation** | Cryptographically verify image provenance and SBOM before applying OS updates | `cosign verify` / Rekor transparency logs |
| **Stateless OS Root** | Non-persistent `/` with explicit persistence for `/var` and `/home` prevents configuration drift | OSTree / bootc container root |
| **Local K8s & Container Parity** | Pre-integrated Podman, Kind/k3d, and container developer toolchains | Containerized toolchains & flatpak isolation |
| **Atomic Rollbacks** | Instant zero-downtime rollback to previous OS deployment if a driver or package update breaks | `bootc rollback` |

---

## Architecture & Workstation Blueprint

```
+-------------------------------------------------------------------+
|               Platform Engineer Workstation (TunaOS)              |
+-------------------------------------------------------------------+
|  Dev Tooling (Flatpak / OCI)  |  Local K8s (Kind/k3d/Podman)       |
+-------------------------------------------------------------------+
|  Immutable Container Root (bootc) - Read-Only system mounts       |
+-------------------------------------------------------------------+
|  Linux Kernel + Hardware Acceleration (NVIDIA / AMD / Intel / Mac)|
+-------------------------------------------------------------------+
```

---

## Quickstart Configuration

### 1. Verifying Image Provenance

Verify OS image signature and SBOM attestation prior to deployment:

```bash
cosign verify \
  --key https://tunaos.org/cosign.pub \
  ghcr.io/tuna-os/tunaos-albacore:latest
```

### 2. Customizing Platform Developer Layers

Enterprise platform teams can build custom workstation layer containerfiles extending TunaOS base images:

```dockerfile
FROM ghcr.io/tuna-os/tunaos-albacore:latest

# Install platform engineering CLI tooling
RUN dnf install -y \
    kubectl \
    helm \
    terraform \
    awscli2 \
    azure-cli \
  && dnf clean all

# Pre-configure enterprise CA certificates and policy defaults
COPY certs/enterprise-ca.crt /etc/pki/ca-trust/source/anchors/
RUN update-ca-trust
```

### 3. Deploying OS Updates via OCI Registries

To pull and stage the latest platform image build:

```bash
sudo bootc update
```

To roll back immediately to the previous functional OS state:

```bash
sudo bootc rollback
```

---

## Security & Compliance Alignment

TunaOS aligns with enterprise security benchmarks (CIS, NIST SP 800-53) for developer endpoints:

1. **Tamper-Proof File System**: System binaries (`/usr`, `/bin`, `/lib`) are mounted read-only and backed by dm-verity / immutable container layers.
2. **SBOM & Vulnerability Scanning**: Base container layers undergo continuous vulnerability scanning in CI/CD before publishing to registry.
3. **Audited Package Sourcing**: RPM packages sourced directly from upstream AlmaLinux 10 / Fedora base repositories.

---

## Community & Engagement

- **GitHub Repository**: [tuna-os/tunaos](https://github.com/tuna-os/tunaos)
- **Matrix Channel**: `#tunaos:reilly.asia`
- **Documentation**: [https://tunaos.org](https://tunaos.org)
