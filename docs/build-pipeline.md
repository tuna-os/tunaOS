# TunaOS Build Pipeline Guide

This document provides a comprehensive overview of the CI/CD pipeline for TunaOS. The pipeline is designed to be automated, robust, and secure, building images weekly for stable releases.

## 🏗️ Architecture Overview

The pipeline builds images on a weekly schedule and publishes them with the `latest` tag. There is no promotion system - weekly builds are considered stable and ready for use.

### Concepts

-   **Variants**: Different OS bases.
    -   `albacore` (AlmaLinux)
    -   `yellowfin` (AlmaLinux Kitten)
-   **Flavors**: Different package sets.
    -   `base`: Minimal OS.
    -   `dx`: Developer Experience (includes dev tools).
    -   `gdx`: Graphical Developer Experience (includes desktop environment and NVIDIA/ZFS support via coreos akmods).

### Hardware Enablement (HWE)

The `gdx` flavor uses the coreos/fedora kernel and akmods for hardware enablement:
-   **NVIDIA drivers**: Provided by `ublue-os/akmods-nvidia-open` using coreos-stable builds
-   **ZFS modules**: Provided by `ublue-os/akmods-zfs` using coreos-stable builds

**Note**: AlmaLinux 10 and AlmaLinux Kitten 10 may require custom ZFS akmods builds since ublue-os/akmods may not fully support these variants yet. The current configuration attempts to use coreos-stable akmods for ZFS on these platforms. If you encounter issues with ZFS on AlmaLinux variants:
- Report issues at https://github.com/tuna-os/tunaOS/issues
- Check the upstream ublue-os/akmods project for AlmaLinux 10 support status
- Consider building custom ZFS akmods for AlmaLinux 10/Kitten if needed

---

## 🔄 Workflows

### 1. Build Weekly Images (`build-next.yml`)

This is the primary build workflow that runs weekly.

-   **Triggers**:
    -   Schedule (Weekly on Tuesdays at 1am UTC).
    -   Manual `workflow_dispatch`.
-   **Process**:
    1.  **Matrix Generation**: Dynamically generates a build matrix for all Variant/Flavor combinations.
    2.  **Build**: Uses `reusable-build-image.yml` to build the container images.
    3.  **Push**: Pushes images to GHCR with the `:latest` tag.
-   **Key Features**:
    -   **Chaining**: Builds `base` first, then uses it as the base for `dx`, and `dx` for `gdx`.

### 2. Pull Request Checks (`build.yml`)

When a Pull Request is opened, the build workflow runs to validate changes.

-   **Triggers**: Pull Request events.
-   **Process**:
    1.  Builds the image from the PR code.
    2.  **Image Diff**: Pulls the current `:latest` image and compares it with the PR image.
    3.  **Reporting**: Posts a comment on the PR detailing:
        -   Added/Removed/Upgraded RPM packages.
        -   File changes in `/usr` and `/etc`.

---

## 🛠️ Scripts & Tools

The pipeline relies on several helper scripts in the `scripts/` directory:

-   **`diff-images.sh`**: Compares two container images and outputs a Markdown report of RPM and file differences. Used in PR checks.
-   **`build-bootc-diskimage.sh`**: A wrapper around `bootc-image-builder` to generate disk images (QCOW2, ISO, etc.) from container images. Requires privileged mode.
-   **`qemu-test.sh`**: Boots a QCOW2 image in QEMU and waits for the SSH port to become active, verifying the image is bootable.

---

## 📖 How-To Guides

### How to Manually Trigger a Build
1.  Go to **Actions** tab in GitHub.
2.  Select **Build Weekly Images**.
3.  Click **Run workflow**.
4.  Optionally select specific Variants or Flavors.
