# High-Performance Computing & Scientific Workstation Guide for TunaOS

> A guide for researchers, HPC engineers, and scientific developers using TunaOS immutable bootc desktop variants.

## Overview

TunaOS provides an immutable, container-native foundation for scientific workstations and High-Performance Computing (HPC) pre/post-processing nodes. By maintaining transactional host immutability through `bootc`, researchers can execute complex computational workloads in isolated containers without degrading host stability.

## Key Advantages for Scientific Workloads

1. **Strict Reproducibility**: Run scientific software stacks (MPI, OpenMP, CUDA, ROCm) inside OCI containers matching cluster runtimes.
2. **Atomic OS Updates**: System updates and driver changes are transactional, eliminating mid-experiment system breakage.
3. **Container-Native Integration**: Full support for Podman, Singularity/Apptainer, and Distrobox for HPC application management.
4. **Base Distro Choice**: Choose enterprise-grade stability via Albacore (AlmaLinux 10 base) or cutting-edge toolchains via Bonito (Fedora base).

## Quick Start & Setup

### Containerized Environment via Apptainer / Podman

Execute containerized HPC workflows with GPU/MPI passthrough:

```bash
# Pull container image for scientific computation
podman pull ghcr.io/tuna-os/albacore-gnome:latest

# Run GPU-accelerated container workload
podman run --device nvidia.com/gpu=all --security-opt label=disable -it ghcr.io/tuna-os/albacore-gnome:latest /bin/bash
```

## Community & Collaboration

Join the scientific computing discussion on `#tunaos:reilly.asia` on Matrix.
