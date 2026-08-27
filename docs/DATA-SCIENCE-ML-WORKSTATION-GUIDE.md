# Data Science & Machine Learning Workstation Guide

> Container-native immutable OS blueprint for AI/ML researchers, data science teams, and GPU-accelerated workstation deployments.

---

## Overview

TunaOS provides bootc-based, container-native desktop operating system images engineered for high-performance computing and reproducible research. For machine learning engineers and data scientists, container-native OS architecture solves driver drift, CUDA compatibility issues, and environment fragmentation by locking GPU drivers, container runtime engines, and base toolchains into versioned OCI image layers.

## Key Advantages for ML & AI Workflows

| Feature | ML/AI Research Benefit | Technical Implementation |
|---|---|---|
| **Immutable GPU Drivers** | Prevents host driver corruption during system updates; locks NVIDIA CUDA / AMD ROCm userspace & kernel modules together | Pre-baked bootc container layers |
| **Reproducible Toolchains** | Guaranteed identical OS and driver baseline across workstation clusters and cloud nodes | OCI image tags (`ghcr.io/tuna-os/...`) |
| **Flatpak & Podman Isolation** | Run JupyterLab, VS Code, and PyTorch/TensorFlow containers without polluting host system directories | Podman + Distrobox + Flatpak |
| **Instant Rollback Safety** | Failed kernel or GPU driver update can be reverted immediately with a single reboot | `bootc rollback` |

---

## Workstation Architecture Blueprint

```
+-------------------------------------------------------------------+
|             AI / Data Science Workstation (TunaOS)                |
+-------------------------------------------------------------------+
|  JupyterLab / VS Code / RStudio  |  Podman Containerized ML Models|
+-------------------------------------------------------------------+
|  CUDA 12.x / ROCm 6.x Userspace Runtime & Container Drivers        |
+-------------------------------------------------------------------+
|  Immutable Container Root (bootc) - Read-Only OS Filesystem       |
+-------------------------------------------------------------------+
|  NVIDIA / AMD Hardware Acceleration & Host Kernel Driver           |
+-------------------------------------------------------------------+
```

---

## Setup & Workflow Guide

### 1. Verifying GPU Driver & Container Acceleration

After booting your TunaOS workstation image, verify containerized GPU passthrough:

```bash
# Check host GPU status
nvidia-smi

# Test containerized GPU passthrough with Podman
podman run --rm --device nvidia.com/gpu=all docker.io/nvidia/cuda:12.3.0-base-ubuntu22.04 nvidia-smi
```

### 2. PyTorch & TensorFlow Container Development

Use Podman or Distrobox to launch isolated Python ML environments without mutating host libraries:

```bash
# Launch a PyTorch 2.x interactive GPU container
podman run --gpus all -it --rm \
  -v $HOME/projects:/workspace \
  -w /workspace \
  pytorch/pytorch:latest python3 -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

### 3. Customizing Team ML Image Layers

Enterprise ML teams can maintain custom containerfiles extending TunaOS:

```dockerfile
FROM ghcr.io/tuna-os/tunaos-albacore:latest

# Pre-install ML system dependencies & libraries
RUN dnf install -y \
    cuda-toolkit \
    libcudnn8 \
    python3-pip \
    gdal-devel \
  && dnf clean all
```

---

## Community & Support

- **Repository**: [tuna-os/tunaos](https://github.com/tuna-os/tunaos)
- **Matrix Channel**: `#tunaos:reilly.asia`
- **Documentation**: [https://tunaos.org](https://tunaos.org)
