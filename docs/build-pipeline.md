# TunaOS Build Pipeline Guide

This document provides a comprehensive overview of the CI/CD pipeline for TunaOS. The pipeline is designed to be automated, robust, and secure, building images on schedule and publishing them with per-flavor tags.

## 🏗️ Architecture Overview

The pipeline builds images on a weekly schedule (Tuesdays at 1am UTC) and publishes them with the `<flavor>` tag (e.g. `gnome`, `gnome-nvidia`). There is no promotion system — weekly builds are considered stable and ready for use. `latest` no longer exists as a monolith; each flavor has its own tag.

### Variants (5 base OSes)

| Variant | Base | Emoji |
|---|---|---|
| `albacore` | AlmaLinux 10 | 🐟 |
| `yellowfin` | AlmaLinux Kitten 10 | 🐠 |
| `skipjack` | CentOS Stream 10 | 🍣 |
| `bonito` | Fedora 44 | 🎣 |
| `redfin` | RHEL 10 (local-only, not in CI) | — |

### Flavors (4-stage DAG; source of truth: `.github/build-config.yml`)

| Stage | Flavors | Description |
|---|---|---|
| 1 | `base` | Minimal OS (required for all downstream stages) |
| 2 | `base-hwe`, `base-nvidia`, `gnome`, `gnome50`, `cosmic`, `kde`, `niri` | HWE/nvidia base layers + desktop environments |
| 3 | `<de>-hwe`, `<de>-nvidia` (e.g. `gnome-hwe`, `kde-nvidia`) | DE layered on HWE or nvidia base |
| 4 | `gnome-nvidia-hwe` | GNOME + nvidia + HWE combined |

Flavor availability varies per variant — e.g. `bonito` omits `gnome50` and some non-GNOME HWE layers.

### Hardware Enablement (HWE)

HWE is a dedicated `base-hwe` layer (stage 2), not bundled with any desktop. It provides:
- **kernel**: `coreos/fedora` via `ublue-os/akmods`
- **NVIDIA drivers**: `ublue-os/akmods-nvidia-open` using coreos-stable builds

Desktop HWE images (<de>-hwe) layer on `base-hwe` in stage 3. nvidia images (<de>-nvidia) layer on `base-nvidia`, which includes NVIDIA/CUDA tooling from `Containerfile.nvidia` + `Containerfile.hwe`.

---

## 🔄 Workflows

### 1. Unified Build (`build-variant.yml`)

The single build workflow for all variants. Replaces the old per-variant `build-{variant}.yml` workflows.

- **Triggers**:
  - Schedule: weekly on Tuesdays at 1am UTC (per-variant cron)
  - Manual: `workflow_dispatch` with `variant` and `flavor` inputs
  - PR: `pull_request` — builds `gnome` flavor only, `linux/amd64` only, no publish
- **Process**:
  1. **Matrix Generation** (`generate_matrix`): reads `.github/build-config.yml` via `yq` + `jq`, emits one matrix per stage (S1–S4)
  2. **Stage 1** (`build_base`): builds `{variant}:base` for every variant in parallel
  3. **Stage 2** (`build_stage2`): builds `base-hwe`, `base-nvidia`, and all desktop flavors (gnome, kde, niri, cosmic) — runs after all stage 1 complete
  4. **Stage 3** (`build_stage3`): builds `<de>-hwe` and `<de>-nvidia` — runs after all stage 2 complete
  5. **Stage 4** (`build_stage4`): builds `gnome-nvidia-hwe` — runs after all stage 3 complete
  6. **Artifacts** (`build_artifacts_s2`, `build_artifacts_s3`, `build_artifacts_s4`): per-stage artifact jobs build ISOs (via `just iso-tacklebox`) and QCOW2s for combo cells where `build_iso: true` / `build_qcow2: true`. Each stage's artifacts depend only on that stage's image builds.
- **Key Features**:
  - **DAG enforcement**: jobs use `needs` to enforce stage ordering; within a stage, `fail-fast: false`
  - **Multi-platform**: `linux/amd64`, `linux/amd64/v2`, `linux/arm64` (per-variant; skipjack/bonito omit v2)
  - **Cosign signing + SBOM** for all published images
  - PR builds limited to gnome flavor, single arch — keeps PR CI fast (~25 min)

### 2. Pull Request Checks

PRs trigger `build-variant.yml` with `variant=all`, `flavor=gnome`. Only stage 1 runs (PR path short-circuit). The reusable workflow builds the gnome image and pushes it as a non-published test artifact.

Legacy `build.yml` is archived at `.github/workflows/archive/build.yml`.

---

## 🛠️ Scripts & Tools

The pipeline relies on several helper scripts in the `scripts/` directory and Justfile recipes:

- **`reusable-build-image.yml`**: Shared CI job for all image builds — handles podman build, cosign sign, SBOM generate, multi-arch manifest, and GHCR push.
- **`generate_matrix`** (in `build-variant.yml`): `yq` + `jq` pipeline that reads `build-config.yml` and emits per-stage JSON matrices.
- **`build-iso-tacklebox.sh`** + `just iso-tacklebox`: Go-based bootc→ISO builder using `ghcr.io/tuna-os/tacklebox`. Replaces the legacy anaconda-based ISO path.
- **`iso-e2e.sh`**: QEMU+OVMF+KVM end-to-end ISO test harness — boots the live ISO, captures screenshots + serial logs, validates GNOME desktop readiness.
- **`dnf_retry`** (in `build_scripts/lib.sh`): Retries transient EPEL/RPM fetch failures up to 4 attempts with exponential backoff.

---

## 📖 How-To Guides

### How to Manually Trigger a Build
1. Go to **Actions** tab in GitHub.
2. Select **Unified Build** (`build-variant.yml`).
3. Click **Run workflow**.
4. Choose `variant` (or `all`) and `flavor` (or `all`).
5. For per-variant schedules, use one of the per-variant trigger workflows: `Build Yellowfin`, `Build Albacore`, `Build Skipjack`, `Build Bonito`.
