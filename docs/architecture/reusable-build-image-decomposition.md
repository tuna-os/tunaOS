# Architectural Plan: Decomposition of `reusable-build-image.yml`

**Status**: PROPOSED (Architectural Analysis)  
**Tracks**: #1648 (Decompose `reusable-build-image.yml` monolith)  
**Owner**: architect  

---

## Executive Summary

`.github/workflows/reusable-build-image.yml` is the primary OCI build workflow for TunaOS, called by 59 caller workflows (`build-*.yml`, `daily-verify.yml`, `catalog-facts.yml`, `bootc-lifecycle.yml`, etc.).

Over successive development cycles, the file has expanded from **791 lines to 1,229 lines** (+55% growth). It currently mixes multiple distinct operational concerns within two massive jobs (`build_push` and `manifest`):

1. **Tooling & Setup** (runner configuration, `just` / `yq` installation & retries).
2. **OCI Image Build & Layer Caching** (buildah distributed cache, `just build`, telemetry summary).
3. **PR Boot Verification** (KVM setup, `corral` / `iso-e2e.sh` execution, artifact upload).
4. **OCI Image Pushing & Metadata** (GHCR push, rechunk annotation checks, package manifest generation, ORAS push).
5. **SBOM & Attestation** (Syft SBOM generation, validation, artifact upload).
6. **PR Reporting & Feedback** (PR testing instructions, image diff generation, pull request comment post).
7. **Manifest Assembly & Labeling** (multi-arch manifest creation, OpenContainer metadata annotations, manifest push).

---

## Structural Risk Analysis

### Why Monolithic Growth is High Risk
- **Blast Radius**: A single YAML syntax error or step failure in `reusable-build-image.yml` immediately breaks all 13 OS variants and 59 workflow callers.
- **Workflow Permissions Overhead**: The monolith requires broad `contents: read`, `packages: write`, and `id-token: write` permissions across the entire workflow.
- **Review Complexity**: A 1,229-line file with nested bash scripts, inline `jq`/`yq` commands, and conditional branching (`github.event_name == 'pull_request'`) imposes severe cognitive load during code review.
- **Parametrization Deficits**: Hardcoded strings (such as maintainer contact info in OpenContainer labels) cannot be overridden without modifying the central monolith.

---

## Proposed Target Decomposition Architecture

To preserve reliability across all 59 callers while reducing review complexity, `reusable-build-image.yml` will be refactored into a **thin top-level orchestrator** calling composite GitHub Actions located under `.github/actions/`:

```
.github/
├── actions/
│   ├── setup-build-tools/           # Action: Install yq, just with retries
│   ├── build-image-step/            # Action: Pre-pull base image, run just build, collect telemetry
│   ├── verify-boot-pr/              # Action: Setup KVM, run corral/iso-e2e PR boot gate
│   ├── publish-package-manifest/    # Action: Extract package list, validate, push ORAS artifact
│   ├── generate-sbom-spdx/          # Action: Setup Syft, scan squashed image, produce SPDX JSON
│   ├── annotate-oci-metadata/       # Action: Generate OpenContainer labels & ArtifactHub annotations
│   └── post-pr-diff/                # Action: Compute image diff, post PR comment
└── workflows/
    └── reusable-build-image.yml     # Orchestrator (~250-300 lines) calling local composite actions
```

---

## Target Component Breakdown

| Action / Module | Primary Responsibility | Lines Extracted (Est.) | Independent Test Path |
|---|---|---|---|
| `.github/actions/setup-build-tools` | Install `yq` and `just` binaries with exponential retries | ~30 lines | Composite action test |
| `.github/actions/build-image-step` | Execute base image pre-pull, `just build`, measure duration/size | ~60 lines | Isolated build check |
| `.github/actions/verify-boot-pr` | KVM udev setup, `corral` gate execution, artifact upload | ~40 lines | PR workflow test |
| `.github/actions/publish-package-manifest` | `podman run` package enumeration, empty-DB guard, `oras push` | ~60 lines | Post-build artifact test |
| `.github/actions/generate-sbom-spdx` | Syft setup, `timeout`-bounded SPDX scan, schema assertion | ~45 lines | SBOM validation test |
| `.github/actions/annotate-oci-metadata` | Generate JSON labels, artifact hub links, maintainer metadata | ~60 lines | Metadata JSON validation |
| `.github/actions/post-pr-diff` | Compare base vs target image, post PR comment via `thollander` | ~40 lines | PR diff test |

---

## Phased Implementation Roadmap

### Phase 1: Composite Actions for Auxiliary Steps (Low Risk)
- Extract `.github/actions/setup-build-tools` (`just` and `yq` setup).
- Extract `.github/actions/publish-package-manifest` (ORAS package list push).
- Extract `.github/actions/generate-sbom-spdx` (bounded Syft SBOM generation).

### Phase 2: Metadata & Reporting Extraction
- Extract `.github/actions/annotate-oci-metadata` (parameterize maintainer contact info).
- Extract `.github/actions/post-pr-diff` and PR testing instruction steps.

### Phase 3: Core Orchestrator Shrink
- Wrap core build and PR boot verification into dedicated steps.
- Shrink `reusable-build-image.yml` to <300 lines, retaining caller input signatures and outputs.

---

## Verification & Safety Invariants

During refactoring:
1. **Input / Output Contract Integrity**: All 14 input parameters and job outputs (`digest`, `image`, `all_platforms_built`) of `reusable-build-image.yml` must remain unchanged.
2. **Caller Compatibility**: All 59 calling workflow files must continue operating without signature changes.
3. **YAML Schema Validation**: Every extracted composite action and orchestrator file must pass `yaml.safe_load` and `actionlint`.
