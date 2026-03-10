# Unified CI/CD Workflow Specification

## Overview
This specification defines the new matrix-driven CI/CD pipeline for TunaOS, consolidating redundant workflows and optimizing the build process.

## Central Configuration (`.github/build-config.yml`)
A single YAML file will serve as the source of truth for all buildable variants, flavors, and platforms.

### Structure Example:
```yaml
config:
  global_platforms: ["linux/amd64", "linux/arm64"]
  
variants:
  - id: yellowfin
    platforms: ["linux/amd64", "linux/amd64/v2", "linux/arm64"]
    flavors:
      - id: gnome
        build_image: true
        build_iso: true
        build_qcow2: true
      - id: gnome-hwe
        build_image: true
      - id: gnome-gdx
        build_image: true
      - id: kde
        build_image: true
        build_iso: true
```

## Workflow Architecture (`.github/workflows/main-build.yml`)

### Jobs:
1. **`detect_changes`**: Analyzes commit paths to determine which variants and flavors require rebuilding.
2. **`generate_matrix`**:
    - Reads `.github/build-config.yml`.
    - Merges with manual inputs (for `workflow_dispatch`).
    - Outputs a JSON matrix for subsequent jobs.
3. **`build_images`**:
    - Uses the generated matrix.
    - Runs on specialized runners (Ubuntu for amd64, ARM runners for arm64).
    - Calls composite actions for setup and build.
4. **`build_artifacts` (ISO/QCOW2)**:
    - Triggers after successful image builds.
    - Uses the matrix to determine which formats to generate.
    - Uploads to Cloudflare R2 and GitHub Releases.

## Composite Actions
- **`actions/setup-tunaos`**: Handles `just`, `podman`, and `yq` installation.
- **`actions/build-image`**: Executes the `just build` command with proper arguments.
- **`actions/publish-image`**: Manages rechunking, SBOM generation, and signing.

## Benefits
- **Maintainability**: Adding a new variant or flavor only requires updating the YAML config.
- **Efficiency**: Parallel matrix builds reduce total CI time.
- **Consistency**: All flavors use the same underlying build and publish logic.
