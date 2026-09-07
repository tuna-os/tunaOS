# Architecture Decision Record: Delivery Contract for Shared Just Modules

**Status**: ACCEPTED  
**Date**: 2026-08-31  
**Tracks**: [#508](https://github.com/tuna-os/tunaos/issues/508) (Cross-repo Justfile inflation), [#1977](https://github.com/tuna-os/tunaos/issues/1977) (Decide the delivery contract for shared Just modules)  
**Authors**: tuna-os team  

---

## 1. Context & Problem Statement

Multiple repositories across the `tuna-os` organization (`tunaos`, `xfce-linux`, `tromso`, `github-copr`, `ubuntu`, etc.) maintain sizable Justfiles (>300 lines) with duplicate recipes for container lifecycle management, image tagging, VM runners, and artifact packaging.

In [#508](https://github.com/tuna-os/tunaos/issues/508), an initial recommendation proposed centralizing these recipes in a shared repository and importing them via remote URLs:
```just
import 'git@github.com:tuna-os/just-recipes.git'
```

However, `just` does not support remote imports: `import` directives only resolve local file paths relative to the filesystem.

This document records the official delivery contract and architecture decision for distributing and consuming shared Just modules across `tuna-os` repositories.

---

## 2. Decision: Evaluated Delivery Mechanisms

Two viable mechanisms were evaluated to deliver shared Just modules to local file systems:

### Option 1: Pinned Git Submodule / Vendor Checkout + Local Import
A consumer repository defines a git submodule (or uses a dedicated git checkout step in CI/tooling) pointing to `tuna-os/just-recipes` at a pinned commit SHA or tag.

- **Pros**: Native Git version tracking; exact cryptographic commit pinning.
- **Cons**: High developer friction (`git clone --recurse-submodules` required; out-of-sync submodules on branch switching; poor ergonomics for casual and external contributors); complex CI checkout choreography across forks and automation runners.

### Option 2: Copy-Vendored Local Modules with Automated Sync (Selected)
Consumer repositories vend copies of standard shared `.just` files directly into a canonical local directory (`just/vendor/` or `just/`), managed and updated via an automated synchronization script and CI freshness check.

- **Pros**:
  - **Zero setup for developers**: Local `just` commands work out-of-the-box on fresh clones without submodule initialization or network access.
  - **Complete offline resilience**: Works seamlessly in air-gapped or offline development environments.
  - **Explicit reviews**: Upstream recipe updates arrive as plain, diffable pull requests with clear impact analysis.
  - **No fork/permission friction**: Submodules frequently break when PRs come from external fork contributors; vendored files eliminate this class of failures.
- **Cons**:
  - Requires automated sync tooling to prevent drift across repositories.

### Decision Outcome

**Option 2 (Copy-Vendoring with Automated Sync & CI Verification)** is selected as the delivery contract for shared Just modules across the `tuna-os` organization.

---

## 3. Delivery Contract & Specifications

### 3.1. Canonical Local Path and Naming Convention

- Shared modules must be stored under `just/` or `just/vendor/` within each consumer repository.
- Module files must use kebab-case with the `.just` extension (e.g., `just/vendor/disk-image.just`).
- Consumer root `Justfile` imports the module using relative local path syntax:
  ```just
  import? 'just/vendor/disk-image.just'
  ```
  *(Note: Using the optional import `import?` or standard `import` depending on whether the module is mandatory for base operations).*

### 3.2. Script Anchoring and Working Directory Invariants

Per the requirements established in `tests/test_just_modules_resolve_repo_paths.py`:
1. **Repository root anchoring**: Every bash recipe within an imported `.just` module MUST start with:
   ```bash
   cd {{ justfile_directory() }}
   ```
   This guarantees consistent working directory behavior across varying `just` versions (e.g., 1.21.0 vs 1.25+).
2. **Helper script paths**: Any script execution inside imported modules must anchor to the repository root using `{{ justfile_directory() }}/...` rather than bare relative paths (`scripts/...`).

### 3.3. Pinning, Versioning, and Update Workflow

1. The central upstream source of truth will be `tuna-os/just-recipes` (or the canonical root repository providing the modules).
2. Each vendored file must include a top-of-file metadata header indicating upstream provenance:
   ```just
   # @vendor: tuna-os/just-recipes
   # @version: v1.2.0 (commit: abc1234)
   # @synced: 2026-08-31
   ```
3. Updates are pulled into consumer repositories using a standardized update script (`scripts/sync-just-modules.sh`) or automated bot workflows (e.g., weekly sync PRs).

### 3.4. Offline and Local Development Behavior

- Because modules are checked directly into the git tree, all recipes are 100% available offline and locally without running network fetch or installation hooks.
- No dynamic network fetches may occur during recipe parse time.

### 3.5. CI Failure & Drift Detection

- Consumer repositories should maintain a test/lint check (e.g., `test_just_modules_resolve_repo_paths.py`) ensuring all vendored modules comply with directory anchoring and path conventions.
- An optional CI workflow job can run `scripts/sync-just-modules.sh --verify` on scheduled runs to detect upstream module drift or unmerged security fixes.

### 3.6. Ownership and Compatibility Policy

- **SemVer**: Shared modules in upstream `tuna-os/just-recipes` follow Semantic Versioning (`vMAJOR.MINOR.PATCH`).
  - **Breaking changes**: Recipe signature changes or required environment variable changes require a major version bump.
  - **Additive features**: New optional recipe parameters or new modules are minor version bumps.
- **Contract Stability**: Exported recipe names and parameters in shared modules must remain backwards-compatible within a major release.

### 3.7. Rollback and Removal Procedure

- If a shared module causes regressions in a consumer repository, the repository can immediately:
  1. Revert the specific vendored file in git to its previous working version.
  2. Fork/override the recipe locally by removing the `import` and placing a custom implementation in `just/<module>.just` or root `Justfile`.
  3. No coordination with external package registries or submodule pointers is required to unblock builds.

---

## 4. Initial Candidate Interfaces

The first batch of shared interfaces identified for modularization across repositories (without copying implementation immediately into this repo) are:

1. **`buildstream` / `build-engine`**:
   - Common container build invocation, caching controls (`USE_CACHE`), and architecture detection.
2. **`disk-image`** (e.g. `qcow2-build.just`):
   - QCOW2 and RAW image building via `bootc image build-to-qcow2`, loop mount setup, and disk probing.
3. **`vm`** (e.g. `vm-pipeline.just`):
   - Local QEMU/KVM virtual machine test runner, headless boot verification, and port forwarding.

---

## 5. Summary & Next Steps

Follow-up issues in consumer repositories and the creation of `tuna-os/just-recipes` can directly cite this architecture decision (`docs/architecture/shared-just-recipes.md`) without needing to reopen discussions on remote import feasibility or submodule ergonomics.
