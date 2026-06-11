# Unified CI/CD Workflow Specification

> **⚠️ This is a target/aspirational specification — the current implementation differs.**
> The pipeline has evolved during implementation. See [`build-pipeline.md`](build-pipeline.md)
> for the currently deployed architecture. Key differences from this spec:
> - **Orchestrator**: \`build-variant.yml\` (not \`main-build.yml\`)
> - **Matrix generation**: \`generate_matrix\` job (not \`detect_changes\`)
> - **Artifact jobs**: Per-stage \`build_artifacts_s{2,3,4}\` (not single \`build_artifacts\`)
> - **Composite actions**: Single \`build-artifacts\` action (not three separate actions)

## Overview
This specification defines the target design for the matrix-driven CI/CD pipeline
for TunaOS, consolidating redundant workflows and optimizing the build process.

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
      - id: gnome-nvidia
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
4. **`build_artifacts_s{2,3,4}` (ISO/QCOW2 per stage)**:
    - Per-stage artifact jobs: `build_artifacts_s2` (needs stage 2), `build_artifacts_s3` (needs stage 3), `build_artifacts_s4` (needs stage 4).
    - Stage-4 failures do not block stage-2/3 ISOs.
    - Uses per-stage artifact matrices to determine which formats to generate.
    - Uploads to Cloudflare R2 and GitHub Releases.

## Composite Actions
- **`actions/setup-tunaos`**: Handles `just`, `podman`, and `yq` installation.
- **`actions/build-image`**: Executes the `just build` command with proper arguments.
- **`actions/publish-image`**: Manages rechunking, SBOM generation, and signing.

## Benefits
- **Maintainability**: Adding a new variant or flavor only requires updating the YAML config.
- **Efficiency**: Parallel matrix builds reduce total CI time.
- **Consistency**: All flavors use the same underlying build and publish logic.
