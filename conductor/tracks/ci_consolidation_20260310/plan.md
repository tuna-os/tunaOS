# Implementation Plan: CI/CD Consolidation and Optimization

## Phase 1: Research and Specification [checkpoint: 2f15fd1]
- [x] Task: Research existing workflows (Finished researching build.yml, build-iso.yml, and reusable-build-image.yml. Identified consolidation points in matrix generation and reusable steps.) and identify consolidation opportunities
    - [ ] Analyze `build.yml`, `build-iso.yml`, and `reusable-build-image.yml`
    - [ ] Map out the required build matrix for all variants and flavors
- [x] Task: Define the new unified (Created docs/CI_SPEC.md defining the new YAML configuration and workflow structure.) workflow specification
    - [ ] Finalize the structure of the central configuration file
    - [ ] Document the proposed GitHub Actions YAML structure
- [x] Task: Conductor - User Manual Verification 'Phase 1: Research and Specification' (Protocol in workflow.md)

## Phase 2: Implementation of Unified Workflow
- [ ] Task: Create a central configuration file for variants and platforms
    - [ ] Define `.github/build-config.yml` with all variant/flavor combinations
- [ ] Task: Implement a unified GitHub Actions workflow with matrix strategies
    - [ ] Create `.github/workflows/main-build.yml`
    - [ ] Implement the matrix strategy using the central config
- [ ] Task: Migrate build logic from individual workflows to the unified one
    - [ ] Incorporate ISO and VM build steps into the unified workflow
    - [ ] Ensure proper secret handling and container registry logins
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Implementation of Unified Workflow' (Protocol in workflow.md)

## Phase 3: Optimization and Validation
- [ ] Task: Implement composite actions for common CI steps
    - [ ] Create composite actions for `setup-podman`, `setup-just`, and `ghcr-login`
- [ ] Task: Restore and verify CI build functionality for all variants
    - [ ] Trigger test builds for all primary variants
    - [ ] Debug and fix any failures resulting from the recent refactor
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Optimization and Validation' (Protocol in workflow.md)
