# Track Specification: CI/CD Consolidation and Optimization

## Overview
This track aims to streamline the TunaOS CI/CD pipeline by consolidating multiple GitHub Actions workflows into a single, optimized, matrix-based workflow. This follows the proposed changes in `docs/BUILD_IMPROVEMENTS.md` and addresses the need to restore functional CI builds after a recent major refactor.

## Goals
- Consolidate redundant workflows (`build.yml`, `build-iso.yml`, etc.) into a unified workflow.
- Implement a matrix strategy for building different variants and flavors.
- Use a central configuration file for managing build variants and platforms.
- Create reusable composite actions for common CI setup and build steps.
- Restore functional CI builds for all primary variants (Albacore, Yellowfin, etc.).

## Technical Details
- **Unified Workflow:** A single `.github/workflows/build-unified.yml` (or similar) using matrix strategies.
- **Central Configuration:** A YAML file (e.g., `.github/build-config.yml`) defining the build matrix.
- **Composite Actions:** Reusable actions in `.github/actions/` for setup-buildx, login-ghcr, etc.
- **Conditional Logic:** Ensuring builds only trigger for relevant changes (using paths-filter).

## Acceptance Criteria
- All OS variants (Albacore, Yellowfin, Skipjack, Bonito) can be built via the unified CI pipeline.
- Build matrix correctly handles different flavors (Regular, HWE, GDX, KDE).
- Redundant workflow files are removed or archived.
- CI build status is green for all primary branches.
