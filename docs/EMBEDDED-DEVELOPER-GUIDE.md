# Embedded Systems & IoT Developer Guide for TunaOS

> A guide for embedded Linux engineers, firmware developers, and IoT hardware developers using TunaOS immutable bootc desktop variants.

## Overview

TunaOS offers an immutable, container-native base operating system powered by `bootc`. For embedded software and hardware engineers, TunaOS provides a stable, deterministic environment for cross-compilation, flashing target boards, and managing hardware debug tooling.

## Key Advantages for Embedded Systems Workflows

1. **Isolated Toolchains**: Run cross-compilers (GCC ARM, RISC-V, Yocto/OpenEmbedded SDKs) inside dedicated OCI containers without host contamination.
2. **Deterministic USB/Serial Passthrough**: Easily map hardware debug probes (JTAG, OpenOCD, USB-to-Serial adapters) into containerized workspaces.
3. **Atomic Host Updates**: Keep host system updates transactional with `bootc` so host driver changes never break firmware flashing pipelines.
4. **Multi-Architecture Support**: Native support for x86_64, ARM64 (including Apple Silicon / Asahi), and containerized target emulators (QEMU).

## Quick Start & Setup

### Containerized Cross-Compilation Environment

Setup an embedded development environment using Podman:

```bash
# Enter containerized dev environment with USB device access for flashing
podman run --device /dev/ttyUSB0 --device /dev/bus/usb -v $PWD:/workspace -w /workspace -it ghcr.io/tuna-os/albacore-gnome:latest /bin/bash

# Execute cross-compilation or flashing commands inside the container
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf-
```

## Community & Collaboration

Join the embedded systems channel on Matrix: `#tunaos:reilly.asia`.
