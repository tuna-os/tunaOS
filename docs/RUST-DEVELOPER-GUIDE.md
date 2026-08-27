# Rust & Systems Developer Onboarding Guide for TunaOS

> A step-by-step guide for Rust and systems programmers using TunaOS immutable bootc desktop variants.

## Overview

TunaOS provides an immutable, container-native base operating system built on `bootc`. For Rust and systems developers, TunaOS combines transactional OS updates with containerized development environments, making it ideal for building reliable, reproducible software.

## Key Features for Rust Developers

1. **Pre-configured Toolchains**: Containerized developer images with `rustc`, `cargo`, `clippy`, and `rustfmt` pre-installed.
2. **Containerized Workspaces**: Native integration with `podman`, `devcontainer`, and `distrobox` to isolate project builds.
3. **BuildStream & Container-Native Build Support**: Integrated build utilities for cross-compilation and system-level packaging across EL10, Fedora, and Debian base variants.
4. **Atomic OS Rollbacks**: Update or test kernel/system dependencies safely using `bootc switch` and atomic rollbacks.

## Quick Start

### 1. Devcontainer Setup
Initialize your Rust repository with devcontainer support on TunaOS:

```bash
# Clone your Rust repository
git clone https://github.com/your-org/your-rust-project.git
cd your-rust-project

# Launch devcontainer environment
devcontainer up --workspace-folder .
```

### 2. Native Cargo Builds with Podman/Distrobox
If building directly via containerized environments:

```bash
# Create a containerized Rust environment using Distrobox
distrobox create --name rust-dev --image ghcr.io/tuna-os/albacore-gnome:latest
distrobox enter rust-dev

# Run cargo commands inside the containerized environment
cargo build --release
cargo test
```

## Recommended Workflow & Best Practices

- **Keep the Host Immutable**: Avoid installing toolchains directly onto the host root filesystem; rely on containerized devcontainers or user-space `rustup` in `~/.cargo`.
- **Use Cache Volumes for Cargo**: Mount `~/.cargo/registry` and `target` directories when running builds in Podman containers to persist dependency caches.
- **System Dependencies**: For C libraries required by `-sys` crates (e.g. `openssl-sys`, `libudev-sys`), include them in your `.devcontainer/Dockerfile` or container image overlay.

## Community & Support

Join the `#tunaos:reilly.asia` Matrix channel or check out the [TunaOS Documentation](https://github.com/tuna-os/tunaos/tree/main/docs) for more guides and support.
