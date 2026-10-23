# Architectural Plan: Decomposition of `reusable-build-image.yml`

**Status**: IMPLEMENTED (2026-10-23)
**Tracks**: #3061 (supersedes the earlier #1648 analysis)
**Owner**: CI maintainers

---

## Executive Summary

`.github/workflows/reusable-build-image.yml` is the primary OCI build
workflow for TunaOS. The seven operational concerns below now live in local
composite actions; callers and the workflow-level job DAG remain unchanged.

1. **Tooling & Setup** (runner configuration, `just` / `yq` installation & retries).
2. **OCI Image Build & Layer Caching** (buildah distributed cache, `just build`, telemetry summary).
3. **PR Boot Verification** (KVM setup, `corral` / `iso-e2e.sh` execution, artifact upload).
4. **OCI Image Pushing & Metadata** (GHCR push, rechunk annotation checks, package manifest generation, ORAS push).
5. **SBOM & Attestation** (Syft SBOM generation, validation, artifact upload).
6. **PR Reporting & Feedback** (PR testing instructions, image diff generation, pull request comment post).
7. **Manifest Assembly & Labeling** (multi-arch manifest creation, OpenContainer metadata annotations, manifest push).

---

## Risks Addressed

- **Review scope**: Build, SBOM, metadata, package inventory, PR reporting,
  and PR boot-gate changes now have separate action files.
- **Test reachability**: The workflow calls the tested
  `scripts/generate-sbom.sh` implementation instead of carrying an inline
  duplicate.
- **Configuration ownership**: OCI maintainer metadata is passed into its
  action rather than embedded in manifest assembly.
- **Caller stability**: The central workflow retains the job graph and public
  `workflow_call` contract, so callers do not migrate during decomposition.

---

## Implemented Decomposition Architecture

The workflow delegates independently testable operational concerns to composite GitHub Actions under `.github/actions/`:

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
    └── reusable-build-image.yml     # Job DAG, permissions, conditions, and caller contract
```

---

## Component Breakdown

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

## Implementation

### Phase 1: Auxiliary Steps
- [x] Extract `.github/actions/setup-build-tools` (`just` and `yq` setup).
- [x] Extract `.github/actions/publish-package-manifest` (ORAS package list push).
- [x] Extract `.github/actions/generate-sbom-spdx` (bounded Syft SBOM generation).

### Phase 2: Metadata & Reporting
- [x] Extract `.github/actions/annotate-oci-metadata` and parameterize maintainer identity.
- [x] Extract `.github/actions/post-pr-diff` and PR testing instructions.

### Phase 3: Core Build and PR Verification
- [x] Extract the cache/build/telemetry sequence into `.github/actions/build-image-step`.
- [x] Extract the PR KVM/Corral gate into `.github/actions/verify-boot-pr`.
- [x] Keep workflow-call inputs, outputs, job permissions, and promotion dependencies in the orchestrator.

---

## Verification & Safety Invariants

During refactoring:
1. **Input / Output Contract Integrity**: The complete `workflow_call` input
   and output mappings remain unchanged.
2. **Caller Compatibility**: Calling workflows require no signature changes.
3. **YAML Schema Validation**: Every extracted composite action and the
   orchestrator pass YAML validation and `actionlint`.
