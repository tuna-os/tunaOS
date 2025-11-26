# TunaOS Build Pipeline Guide

This document provides a comprehensive overview of the CI/CD pipeline for TunaOS. The pipeline is designed to be automated, robust, and secure, moving images through a defined promotion strategy from `next` to `testing` to `stable`.

## 🏗️ Architecture Overview

The pipeline consists of three main stages, corresponding to the three channels:

1.  **Next (`:next`)**: The bleeding edge. Built frequently (on push to main or schedule).
2.  **Testing (`:testing`)**: The candidate for release. Promoted weekly after passing automated QA.
3.  **Stable (`:stable`)**: The official release. Promoted from testing via Git tags.

### Concepts

-   **Variants**: Different OS bases.
    -   `albacore` (AlmaLinux)
    -   `yellowfin` (AlmaLinux Kitten)
-   **Flavors**: Different package sets.
    -   `base`: Minimal OS.
    -   `dx`: Developer Experience (includes dev tools).
    -   `gdx`: Graphical Developer Experience (includes desktop environment).

---

## 🔄 Workflows

### 1. Build Next Image (`build-next.yml`)

This is the primary build workflow.

-   **Triggers**:
    -   Push to `main`.
    -   Schedule (Daily).
    -   Manual `workflow_dispatch`.
-   **Process**:
    1.  **Matrix Generation**: Dynamically generates a build matrix for all Variant/Flavor combinations.
    2.  **Build**: Uses `reusable-build-image.yml` to build the container images.
    3.  **Push**: Pushes images to GHCR with the `:next` tag.
-   **Key Features**:
    -   **Chaining**: Builds `base` first, then uses it as the base for `dx`, and `dx` for `gdx`.

### 2. Pull Request Checks (`reusable-build-image.yml`)

When a Pull Request is opened, the build workflow runs in a special mode.

-   **Triggers**: Pull Request events.
-   **Process**:
    1.  Builds the image from the PR code.
    2.  **Image Diff**: Pulls the current `:next` image and compares it with the PR image.
    3.  **Reporting**: Posts a comment on the PR detailing:
        -   Added/Removed/Upgraded RPM packages.
        -   File changes in `/usr` and `/etc`.

### 3. Promote to Testing (`promote-to-testing.yml`)

This workflow manages the promotion from `next` to `testing`.

-   **Triggers**:
    -   Schedule (Weekly, e.g., Mondays).
    -   Manual `workflow_dispatch`.
-   **Process**:
    1.  **Candidate Selection**: Identifies the latest successful `build-next` run.
    2.  **QA & Verification**:
        -   **SBOM**: Generates a Software Bill of Materials using `syft`.
        -   **QEMU Boot Test**: Builds a QCOW2 disk image from the container and boots it in QEMU to verify system integrity.
    3.  **Manual Gate**: Pauses for approval in the `manual-approval` Environment.
    4.  **Promotion**: Upon approval, retags the specific image digest to `:testing`.
    5.  **Summary**: Outputs a summary of promoted images.

### 4. Release Stable (`release-stable.yml`)

This workflow handles the final release.

-   **Triggers**:
    -   Push of a tag matching `*-YYYYMMDD.x` (e.g., `albacore-20251126.0`).
-   **Process**:
    1.  **Validation**: Parses the tag to identify the Variant/Flavor.
    2.  **Artifact Generation**: Builds a QCOW2 disk image from the `:testing` image.
    3.  **Upload**: Uploads the QCOW2 to S3.
    4.  **Promotion**: Retags the `:testing` image to `:stable` and the versioned tag (e.g., `:20251126.0`).

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
2.  Select **Build Next Image**.
3.  Click **Run workflow**.
4.  Optionally select specific Variants or Flavors.

### How to Approve a Promotion
1.  When `promote-to-testing` runs, it will pause at the "Promote to Testing" job.
2.  Click **Review deployments**.
3.  Check the **Promotion Candidate** summary in the workflow run.
4.  Click **Approve and deploy**.

### How to Cut a Stable Release
1.  Ensure the `:testing` image is the one you want to release.
2.  Create and push a git tag:
    ```bash
    git tag albacore-20251126.0
    git push origin albacore-20251126.0
    ```
3.  The `release-stable` workflow will trigger automatically.
