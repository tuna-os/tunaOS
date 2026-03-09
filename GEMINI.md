# TunaOS - Gemini Context

## Project Overview
TunaOS is a curated collection of Cloud-Native Enterprise Linux OS Images. It provides Bootc-based desktop operating systems that are forks of [Bluefin LTS](https://github.com/ublue-os/bluefin-lts), built on modern container technology. The project explores the flexibility of Bootc to provide a stable enterprise Linux desktop experience with up-to-date GNOME (and KDE) and modern tooling like Homebrew and Flathub out of the box.

### Key Variants
- **Albacore:** Based on AlmaLinux 10.0. Stable enterprise-grade desktop.
- **Yellowfin:** Based on AlmaLinux Kitten 10. Closest to upstream Bluefin LTS experience.
- **Bonito:** Based on Fedora 42 (experimental/in progress).
- **Skipjack:** Based on CentOS 10.

### Image Flavors
Each variant ships in multiple flavors:
- **Base/Regular:** Standard GNOME desktop.
- **HWE (Hardware Enablement):** Newer kernel stack and hardware support profile.
- **GDX (Graphical Developer Experience):** Includes NVIDIA drivers and CUDA.
- **KDE:** Plasma desktop builds (also available as `-kde-hwe` and `-kde-gdx`).

## Technologies & Architecture
- **Core:** [Bootc](https://github.com/bootc-dev/bootc) (bootable containers).
- **Build System:** `Just` (command runner), Shell scripts, `Podman` (for local builds).
- **CI/CD:** GitHub Actions (for automated ISO and image builds).
- **Directory Structure:**
  - `build_scripts/`: Shell scripts used during the container build process to install packages, configure services, etc.
  - `system_files/`: Configuration files and scripts overlaid onto the system root (`/etc`, `/usr/share/ublue-os`, etc.).
  - `system_files_overrides/`: Specific overrides for different flavors like `dx`, `gdx`, and `kde`.
  - `scripts/`: Helper scripts for building images, disk images (qcow2), running local CI, and testing VMs.

## Building and Running

The project relies heavily on the `Justfile` to orchestrate builds. Ensure `just`, `podman`, and `yq` are installed for local development.

### Key Commands

- **List available commands:**
  ```bash
  just
  ```
- **Check syntax (Shell, YAML, JSON, Just):**
  ```bash
  just check
  ```
- **Build a specific variant and flavor:**
  ```bash
  just build <variant> <flavor>
  # Example: just build yellowfin base
  # Example: just build albacore kde-gdx
  ```
- **Build a VM image (qcow2):**
  ```bash
  just qcow2 <variant> <flavor>
  ```
- **Test in a VM:**
  ```bash
  just test-vm <variant> <flavor>
  # Default VM credentials are user: "centos", password: "centos"
  ```
- **Clean build artifacts:**
  ```bash
  just clean
  ```

## Development Conventions
- **Shell Scripts:** Heavy reliance on shell scripting. Scripts should be checked with `shellcheck` and formatted with `shfmt` (via `just check` and `just fix`).
- **Containerfiles:** Multiple Containerfiles exist for different flavors (e.g., `Containerfile`, `Containerfile.hwe`, `Containerfile.kde`). Builds heavily use `--build-arg` to customize base images and vendor information.
- **Testing:** Local VM testing is supported via `qemu` through the `just test-vm` wrapper.
- **CI Pipelines:** Look at `.github/workflows` to understand the full automated build matrix. Changes should ensure they pass the existing syntax and build checks.
