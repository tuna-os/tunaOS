# Initial Concept

TunaOS is a curated collection of Cloud-Native Enterprise Linux OS Images. It provides Bootc-based desktop operating systems that are forks of [Bluefin LTS](https://github.com/ublue-os/bluefin-lts), built on modern container technology.

# TunaOS - Product Guide

## Initial Concept
TunaOS is a curated collection of Cloud-Native Enterprise Linux OS Images. It provides Bootc-based desktop operating systems that are forks of [Bluefin LTS](https://github.com/ublue-os/bluefin-lts), built on modern container technology.

## Product Vision
TunaOS aims to bridge the gap between stable enterprise Linux and a modern desktop experience. By leveraging [Bootc](https://github.com/bootc-dev/bootc) (bootable containers), it provides a stable foundational OS while delivering up-to-date GNOME features, modern CLI tools through Homebrew, and a rich app ecosystem via Flathub.

## Target Audience
- **Enterprise Users:** Seeking a rock-solid, stable operating system for professional environments without sacrificing modern desktop capabilities.
- **General Linux Users:** Looking for a polished, out-of-the-box desktop experience that is easy to manage and update.

## Core Value Propositions
- **Modern GNOME on Stable Base:** Shipping the latest GNOME features (e.g., GNOME 48.3) on enterprise-grade bases like AlmaLinux 10, avoiding the typically outdated software in traditional EL distributions.
- **Cloud-Native Desktop Experience:** Utilizing bootable containers to manage the operating system as a versioned, immutable image, simplifying updates and rollbacks.
- **Modern Tooling Out-of-the-Box:** Integrating Homebrew for CLI applications and Flathub for graphical software directly into the image for a seamless user experience.

## Strategic Focus
- **AlmaLinux-based Variants:** Prioritizing Albacore (AlmaLinux 10.0) and Yellowfin (AlmaLinux Kitten 10) to provide the most stable and compatible enterprise foundation.
- **Distribution:** Primary delivery via GitHub Container Registry (GHCR) and optimized custom ISOs for straightforward installation.

## Functional Goals
- Maintain feature parity with upstream Bluefin LTS and Bluefin.
- Provide a robust hardware enablement (HWE) stack and specialized flavors for NVIDIA (GDX) and KDE Plasma users.
- Automate image and ISO builds using GitHub Actions for consistent releases.