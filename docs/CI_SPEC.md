# Unified CI/CD Workflow Specification

> **⚠️ This is a target/aspirational specification — the current implementation differs.**
> The pipeline has evolved during implementation. See [`build-pipeline.md`](build-pipeline.md)
> for the currently deployed architecture. Key differences from this spec:
> - **Orchestrator**: \`build-variant.yml\` (not \`main-build.yml\`)
> - **Matrix generation**: \`generate_matrix\` job (not \`detect_changes\`)
> - **Artifact jobs**: Per-stage \`build_artifacts_s{2,3,4}\` (not single \`build_artifacts\`)
> - **Composite actions**: Single \`build-artifacts\` action (not three separate actions)

<!-- BEGIN GENERATED CI LANES — scripts/gen-ci-lanes.py -->

## Executing workflow lanes

This inventory is generated from workflow triggers and `.github/green-criteria.yml`; run `scripts/gen-ci-lanes.py` after changing either. **PR-deterministic** is fast contributor feedback. **Post-merge** publishes or reacts to trusted repository events. **Scheduled** independently revalidates state and freshness.

| Workflow | Lane | Assertion | Cadence | Freshness SLA |
|---|---|---|---|---|
| `arm64-ulimit-probe.yml` | PR-deterministic + post-merge | arm64 ulimit probe (diagnostic) | each PR, manual | — |
| `asahi-hw-nightly-one.yml` | post-merge + scheduled | Asahi hardware smoke (one) | caller cadence | — |
| `asahi-hw-nightly.yml` | post-merge + scheduled | Asahi hardware smoke (Tier 2 rental) | `0 6 * * *`, manual | — |
| `audit-nvidia-release-assets.yml` | post-merge + scheduled | Audit NVIDIA release assets | `30 0 * * *`, manual | — |
| `bootc-lifecycle.yml` | post-merge + scheduled | `lifecycle` | `0 5 * * 4`, manual | `lifecycle`: 8d |
| `build-albacore.yml` | post-merge + scheduled | Build Albacore | `20 2 * * *`, manual | — |
| `build-archlinuxarm-base.yml` | post-merge + scheduled | Build Arch Linux ARM base | push, `40 2 * * 1`, manual | — |
| `build-bonito-rawhide.yml` | post-merge + scheduled | Build Bonito-rawhide | `20 15 * * *`, manual | — |
| `build-bonito.yml` | post-merge + scheduled | Build Bonito | `20 11 * * *`, manual | — |
| `build-flavor.yml` | post-merge | Build Flavor | manual | — |
| `build-flounder-sid.yml` | post-merge + scheduled | Build Flounder-sid | `20 23 * * *`, manual | — |
| `build-flounder.yml` | post-merge + scheduled | Build Flounder | `20 21 * * *`, manual | — |
| `build-grouper.yml` | post-merge + scheduled | Build Grouper | `20 17 * * *`, manual | — |
| `build-guppy.yml` | post-merge + scheduled | Build Guppy | `20 6 * * *`, manual | — |
| `build-gurnard.yml` | post-merge + scheduled | Build Gurnard | `20 4 * * *`, manual | — |
| `build-hummingbird.yml` | post-merge + scheduled | Build Hummingbird | `20 22 * * *`, manual | — |
| `build-marlin.yml` | post-merge + scheduled | Build Marlin | `20 13 * * *`, manual | — |
| `build-sailfin.yml` | post-merge + scheduled | Build Sailfin | `20 19 * * *`, manual | — |
| `build-skipjack.yml` | post-merge + scheduled | Build Skipjack | `20 9 * * *`, manual | — |
| `build-toolchain.yml` | post-merge | build-toolchain | push, manual | — |
| `build-variant.yml` | post-merge + scheduled | Unified Build | caller cadence | — |
| `build-wahoo.yml` | post-merge | Build Wahoo [experimental] | manual | — |
| `build-yellowfin.yml` | post-merge + scheduled | Build Yellowfin | `20 0 * * *`, manual | — |
| `catalog-facts.yml` | post-merge + scheduled | Catalog Facts | `0 6 * * *`, manual | — |
| `check-base-image-pins.yml` | post-merge + scheduled | `rebuildable`, `arch_honesty` | `20 22 * * *`, manual | `rebuildable`: 2d, `arch_honesty`: 2d |
| `check-download-checksums.yml` | PR-deterministic + post-merge + scheduled | Check download checksums | each PR, `35 22 * * *`, manual | — |
| `content-filter.yaml` | post-merge | Check for Spammy Issue Comments | issue_comment | — |
| `daily-verify.yml` | post-merge + scheduled | Daily Image Verification | `0 4 * * *`, manual | — |
| `desktop-contract-sweep.yml` | post-merge + scheduled | `desktop`, `no_silent_omissions` | `0 8 * * *`, manual | `desktop`: 2d, `no_silent_omissions`: 2d |
| `drop-bot-review-requests.yml` | PR-deterministic | Drop bot review requests | each PR | — |
| `frontend-parity.yml` | post-merge + scheduled | frontend parity | `30 6 * * *`, manual | — |
| `gdm-paint-benchmark.yml` | post-merge | GDM Paint Benchmark | manual | — |
| `generate-changelog-release.yml` | post-merge + scheduled | Generate Release | `05 11 * * *`, manual | — |
| `ghcr-partial-pull-check.yml` | post-merge + scheduled | GHCR Partial-Pull Compatibility Canary | `30 8 * * 1`, manual | — |
| `graduation-check.yml` | post-merge + scheduled | Graduation Check | `0 7 * * 1`, manual | — |
| `installer-fisherman-pins.yml` | PR-deterministic + post-merge + scheduled | Installer fisherman pins | each PR, `0 5 * * *`, manual | — |
| `installer-screenshots.yml` | post-merge + scheduled | Installer Walkthrough Screenshots | `0 5 * * 1`, manual | — |
| `installer-smoke.yml` | post-merge | Installer Smoke | manual | — |
| `iso-builder-parity.yml` | post-merge | ISO Builder Parity | caller cadence | — |
| `iso-e2e.yml` | PR-deterministic + post-merge + scheduled | `iso` | each PR, `0 6 * * 1`, manual | `iso`: 8d |
| `just-fix.yml` | PR-deterministic + post-merge | Just Fix | each PR, push | — |
| `lint.yml` | PR-deterministic + post-merge | Lint and Check | each PR, push | — |
| `live-initramfs.yml` | post-merge | Live Initramfs Artifacts | manual | — |
| `live-iso-bootc.yml` | PR-deterministic + post-merge | Live ISOs (Tacklebox) | each PR, manual | — |
| `live-overlay.yml` | post-merge + scheduled | Live Overlay Artifacts | `30 9 * * 3`, manual | — |
| `luks-e2e.yml` | post-merge + scheduled | `install` | `0 7 1 * *`, `0 7 1 */3 *`, manual, caller cadence | `install`: 35d |
| `matrix-status.yml` | PR-deterministic + post-merge + scheduled | Matrix Status | each PR, `0 6 * * *`, manual | — |
| `package-parity.yml` | post-merge + scheduled | `parity` | `40 8 * * *`, manual | `parity`: 2d |
| `post-build-luks-e2e.yml` | post-merge + scheduled | Post-Build LUKS E2E | `0 6 * * 4`, workflow completion, manual | — |
| `pr-nudges.yml` | PR-deterministic | PR Reminders | each PR | — |
| `prune-r2.yml` | post-merge + scheduled | Prune R2 retention | `30 12 * * *`, manual | — |
| `publish-iso-groups.yml` | post-merge + scheduled | Publish Grouped Dedup ISOs to R2 | `0 23 * * 0`, manual | — |
| `publish-isos.yml` | post-merge | Publish Live ISOs to R2 | manual | — |
| `randomized-tests.yml` | post-merge + scheduled | Randomized Tests | `30 3 * * *`, manual | — |
| `rerun-infra-failures.yml` | post-merge | Re-run infra failures | workflow completion, manual | — |
| `rerun-startup-failures.yml` | post-merge + scheduled | Re-run startup failures | `0 */3 * * *`, manual | — |
| `reusable-build-artifacts.yml` | post-merge + scheduled | Artifacts | caller cadence | — |
| `reusable-build-image.yml` | post-merge + scheduled | `builds`, `desktop`, `boots`, `no_silent_omissions` | caller cadence | `builds`: 2d, `desktop`: 2d, `boots`: 2d, `no_silent_omissions`: 2d |
| `scorecard.yml` | post-merge + scheduled | Scorecard supply-chain security | push, `38 0 * * 4`, branch_protection_rule | — |
| `snapshot-upstreams.yml` | post-merge + scheduled | Snapshot upstreams | `0 9 * * 1`, manual | — |
| `test.yml` | PR-deterministic + post-merge | Test | each PR, push, manual | — |
| `update-build-status.yml` | post-merge + scheduled | Update README build status | `30 13 * * *`, manual | — |
| `validate-renovate.yaml` | PR-deterministic + post-merge | Validate Renovate Config | each PR, push | — |
| `verify-asahi-one.yml` | post-merge + scheduled | Verify Asahi image (one) | caller cadence | — |
| `verify-asahi.yml` | post-merge + scheduled | Verify Asahi image | `40 5 * * *`, manual | — |
| `watch-aurora.yml` | post-merge + scheduled | Watch Aurora Upstream | `0 8 * * 1`, manual | — |
| `watch-bluefin-lts.yml` | post-merge + scheduled | Watch bluefin-lts Upstream | `0 8 * * 1`, manual | — |
| `watch-upstream.yml` | post-merge + scheduled | Watch upstream (reusable) | caller cadence | — |
| `watch-zirconium.yml` | post-merge + scheduled | Watch Zirconium Upstream | `0 8 * * 1`, manual | — |
| `weekly-boot-report.yml` | post-merge + scheduled | Weekly Boot Screenshot Report | `0 10 * * 1`, manual | — |
| `weekly-desktop-screenshots.yml` | post-merge + scheduled | Weekly Desktop Screenshots | `0 2 * * 1`, manual | — |
| `weekly-qcow2-screenshots.yml` | post-merge + scheduled | Weekly QCOW2 Boot Screenshots | `0 20 * * 0`, manual | — |

<!-- END GENERATED CI LANES -->

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
