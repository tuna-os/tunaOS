# Bioinformatics & Computational Biology Guide for TunaOS

> A guide for computational biologists, bioinformaticians, and life sciences researchers using TunaOS immutable bootc desktop variants.

## Overview

TunaOS provides an immutable, container-native base OS built on `bootc`. For bioinformatics and genomic research, TunaOS combines host-level stability with containerized isolation for complex software stacks (BioPython, R/Bioconductor, Conda/Mamba, Nextflow, Snakemake).

## Key Advantages for Bioinformatics Workflows

1. **Pipeline Reproducibility**: Run workflow managers (Nextflow, Snakemake) inside containerized environments matching cloud/HPC execution targets.
2. **Environment Isolation**: Avoid host library pollution when managing multiple Python/Conda environments or tool versions.
3. **Atomic OS Upgrades**: System updates remain transactional, protecting long-running sequence processing jobs from host breakage.
4. **Base Stability Options**: Albacore (AlmaLinux 10 base) for multi-year stability or Bonito (Fedora base) for recent toolchains.

## Quick Start & Setup

### Running Nextflow / Conda Containers

Spin up a containerized bioinformatics environment:

```bash
# Pull container environment for pipeline development
podman run -v $PWD:/data -w /data -it ghcr.io/tuna-os/albacore-gnome:latest /bin/bash

# Execute Nextflow or Conda workflows inside container
nextflow run main.nf -profile docker
```

## Community & Support

Join the Matrix channel `#tunaos:reilly.asia` for bioinformatics and research discussions.
