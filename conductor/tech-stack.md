# TunaOS - Tech Stack

## Core Technology
TunaOS is built on **Bootc (bootable containers)**, a modern approach to managing the operating system as a versioned, immutable container image. This allows for transactional updates and rollbacks, simplifying OS lifecycle management.

## Base OS Distributions
- **AlmaLinux 10:** The primary enterprise-grade stable base (Albacore).
- **AlmaLinux Kitten 10:** The AlmaLinux development-stream base (Yellowfin).
- **CentOS 10 (Skipjack):** A community-driven enterprise base that is **closest to upstream Bluefin-LTS**.
- **Fedora (Bonito):** The cutting-edge base for new feature exploration.
- **Red Hat Enterprise Linux (RHEL):** Known as **Redfin**, this variant is for internal/authorized use and cannot be publicly redistributed. No ISOs or images for Redfin are published on GHCR.

## Build & Local Development
- **Just:** A command runner (`Justfile`) used to orchestrate builds, tests, and maintenance tasks.
- **Shell (Bash):** Extensively used for build scripts, configuration overlays, and system-level customization.
- **Podman:** Used for local container builds and image management.
- **yq:** For processing YAML/TOML configuration files during the build process.

## Desktop Environments & UI
- **GNOME:** The default desktop environment, featuring the latest backported features.
- **KDE Plasma:** Available as specialized flavors for users who prefer the Plasma desktop.

## Software Distribution & Packaging
- **Homebrew:** Integrated into the base image for straightforward CLI tool management.
- **Flathub:** Enabled by default to provide a vast ecosystem of graphical applications.

## CI/CD & Automation
- **GitHub Actions:** Automates the build and distribution of container images and bootable ISOs.
- **Cosign:** Used for signing images to ensure provenance and security.

## Testing & Verification
- **QEMU/KVM:** Leveraged for VM-based testing and verification of images and ISOs.
