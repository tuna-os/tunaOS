# Architecture Decision Record: Delivery Contract for Shared Just Modules

**Status**: ACCEPTED  
**Date**: 2026-08-31  
**Tracks**: [#508](https://github.com/tuna-os/tunaos/issues/508) (Cross-repo Justfile inflation), [#1977](https://github.com/tuna-os/tunaos/issues/1977) (Decide the delivery contract for shared Just modules)  
**Authors**: tuna-os team  

---

## 1. Context & Problem Statement

Multiple repositories across the `tuna-os` organization (`tunaos`, `xfce-linux`, `tromso`, `github-copr`, `ubuntu`, etc.) maintain sizable Justfiles (>300 lines) with duplicate recipes for container lifecycle management, image tags, VM runners, and artifact assembly.

In [#508](https://github.com/tuna-os/tunaos/issues/508), an initial recommendation proposed a shared repository for these recipes, with an import through remote URLs:
```just
import 'git@github.com:tuna-os/just-recipes.git'
```

However, `just` does not support remote imports: `import` directives resolve only local file paths, relative to the filesystem.

This document records the official delivery contract and architecture decision. It covers how the `tuna-os` repositories distribute and consume the shared `just` modules.

---

## 2. Decision: Evaluated Delivery Mechanisms

We evaluated two mechanisms that deliver shared `just` modules to local file systems. Both are viable:

### Option 1: Pinned Git Submodule / Vendor Checkout + Local Import
A consumer repository defines a git submodule that points to `tuna-os/just-recipes` at a pinned commit SHA or tag. A dedicated step that runs `git checkout` in CI or tooling does the same job.

- **Pros**: Git tracks the version natively; the commit pin is exact and cryptographic.
- **Cons**: High developer friction. It needs `git clone --recurse-submodules`. Submodules go out of sync when you switch branch. Ergonomics are poor for casual and external contributors. CI checkout choreography is complex across forks and automation runners.

### Option 2: Copy-Vendored Local Modules with Automated Sync (Selected)
A consumer repository vends its copies of the standard shared `.just` files. The copies go into a canonical local directory (`just/vendor/` or `just/`). An automated synchronization script and a CI freshness check keep them up to date.

- **Pros**:
  - **Zero setup for developers**: Local `just` commands work out-of-the-box on fresh clones without submodule initialization or network access.
  - **Complete offline resilience**: Works without problems in air-gapped or offline development environments.
  - **Explicit reviews**: Updates to upstream recipes arrive as plain, diffable pull requests with clear impact analysis.
  - **No fork/permission friction**: Submodules frequently break when PRs come from external fork contributors. Vendored files eliminate this class of failures.
- **Cons**:
  - Needs automated sync tooling to prevent drift across repositories.

### Decision Outcome

We select **Option 2 (copy-vendored local modules with automated sync and CI verification)** as the delivery contract for shared `just` modules across the `tuna-os` organization.

---

## 3. Delivery Contract & Specifications

### 3.1. Canonical Local Path and Naming Convention

- Each consumer repository must store shared modules under `just/` or `just/vendor/`.
- Module files must use kebab-case with the `.just` extension (e.g., `just/vendor/disk-image.just`).
- Consumer root `Justfile` imports the module with a relative local path:
  ```just
  import? 'just/vendor/disk-image.just'
  ```
  *(Note: use the optional `import?` when the module is optional. Use standard `import` when the module is mandatory for base operations.)*

### 3.2. Script Anchoring and Working Directory Invariants

Per the requirements established in `tests/test_just_modules_resolve_repo_paths.py`:
1. **Anchor to the repository root**: Every bash recipe in an imported `.just` module MUST start with:
   ```bash
   cd {{ justfile_directory() }}
   ```

   This line guarantees the same directory behavior on every `just` version (e.g., 1.21.0 vs 1.25+).
2. **Helper script paths**: Any script call inside an imported module must anchor to the repository root. Use `{{ justfile_directory() }}/...` instead of bare relative paths (`scripts/...`).

### 3.3. Pinning, Versioning, and Update Workflow

1. The central upstream source of truth will be `tuna-os/just-recipes` (or the canonical root repository that provides the modules).
2. Each vendored file must include a top-of-file metadata header that names its upstream source:
   ```just
   # @vendor: tuna-os/just-recipes
   # @version: v1.2.0 (commit: abc1234)
   # @synced: 2026-08-31
   ```
3. A standardized update script (`scripts/sync-just-modules.sh`) pulls updates into consumer repositories. Automated bot workflows can also pull them (e.g., weekly sync PRs).

### 3.4. Offline and Local Development Behavior

- The git tree holds the modules directly. Every recipe is therefore 100% available offline and locally, with no network fetch and no installation hooks.
- No dynamic network fetches may occur during recipe parse time.

### 3.5. CI Failure & Drift Detection

- Consumer repositories should maintain a test/lint check (e.g., `test_just_modules_resolve_repo_paths.py`). The check confirms that all vendored modules comply with the conventions for directory anchors and paths.
- An optional job in CI can run `scripts/sync-just-modules.sh --verify` on scheduled runs. The job detects drift in upstream modules, or unmerged security fixes.

### 3.6. Ownership and Compatibility Policy

- **SemVer**: Shared modules in upstream `tuna-os/just-recipes` follow the SemVer scheme (`vMAJOR.MINOR.PATCH`).
  - **Changes that break the contract**: a change to a recipe signature needs a major version bump. So does a change to a required environment variable.
  - **Additive features**: New optional recipe parameters or new modules are minor version bumps.
- **Contract Stability**: Exported recipe names and parameters in shared modules must remain backwards-compatible within a major release.

### 3.7. Rollback and Removal Procedure

- If a shared module causes a regression in a consumer repository, that repository can immediately:
  1. Revert the specific vendored file in git to the last version that worked.
  2. Fork or override the recipe locally: remove the `import`, then put a custom implementation in `just/<module>.just` or the root `Justfile`.
  3. No coordination with external package registries or submodule pointers is required to unblock builds.

---

## 4. Initial Candidate Interfaces

The first batch of shared interfaces identified for modularization across repositories (with no immediate copy of the implementation into this repo) are:

1. **`buildstream` / `build-engine`**:
   - Common container build invocation, cache controls (`USE_CACHE`), and architecture detection.
2. **`disk-image`** (e.g. `qcow2-build.just`):
   - QCOW2 and RAW image builds via `bootc image build-to-qcow2`, loop mount setup, and disk probes.
3. **`vm`** (e.g. `vm-pipeline.just`):
   - Local test runner for QEMU/KVM virtual machines, headless boot verification, and port forward setup.

---

## 5. Summary & Next Steps

Follow-up issues in consumer repositories can directly cite this architecture decision (`docs/architecture/shared-just-recipes.md`). So can the creation of `tuna-os/just-recipes`. No one needs to reopen the discussion about remote import feasibility or submodule ergonomics.
