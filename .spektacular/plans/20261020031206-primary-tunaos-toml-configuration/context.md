---
created_date: "2026-10-20"
document_status: draft
---

# Context: 20261020031206-primary-tunaos-toml-configuration

## Current State Analysis

Baseline main is 83362754. The matrix authority was .github/build-config.yml; scripts/lib/build-config.sh:6 provides an existing shell seam, while direct workflow reads require preparation in each checkout. scripts/prepare-fork-config.py:135 copies only tracked sources, so ignored adapters must be generated inside each resulting context. scripts/resolve-fork-config.py:74 receipts source bytes and must attest TOML and generator code.

Implementation is being developed in parallel. This document is a plan, not a completion record. The core suite passed 65 cases on actual Python 3.10.22 with tomli 2.2.1 and Python 3.12 with tomllib. Full-suite checks continue; image/install qualification is not claimed here.

## Per-Phase Technical Notes

### Phase 1.1: Capture complete matrix ownership

**File changes:** tunaos.toml:1; tests/fixtures/primary-config/matrix-before-migration.json:1; tests/fixtures/primary-config/bonito-gnome-x13s.toml:1. Capture all 14 variants and 155 declared flavor records at the recorded baseline; preserve omitted flags and comments.

**Complexity:** Medium

**Token estimate:** ~10k tokens

**Agent strategy:** 2–3 parallel agents for independent changes.

### Phase 1.2: Generate and consume the matrix safely

**File changes:** scripts/lib/tunaos_config.py:1–205; scripts/config.py:1–34; scripts/lib/build-config.sh:6; scripts/resolve-fork-config.py:74–95,171–198; scripts/prepare-fork-config.py:135–175; .github/actions/prepare-config/action.yml:1; .github/actions/setup-yq/action.yml:70; .github/workflows/reusable-build-image.yml:168,963,994; .github/workflows/build-flavor.yml:28; .github/workflows/desktop-contract-sweep.yml:51; .github/workflows/matrix-status.yml:22,64; .github/workflows/weekly-boot-report.yml:41; renovate.json:82–110; just/utilities.just:1–240; tests/test_primary_config.py:1. Direct Python loaders and get-base-image/audit shell scripts must use the shared core/seam. Remove tracked .github/build-config.yml only after these paths are covered; ignore the derived path. Source receipts include TOML and generator, not derived bytes. Add python3 to Wolfi dependencies.

**Complexity:** High

**Token estimate:** ~25k tokens

**Agent strategy:** Parallel analysis, sequential integration.

### Phase 2.1: Move native package and repository policy

**File changes:** tunaos.toml:1 (extend schema); scripts/lib/tunaos_config.py:64–149 (extend validated surface); manifests/desktops/gnome.yaml:1 and remaining manifests/desktops/*.yaml:1 (migrate reviewed profiles); build_scripts/10-base-packages.sh:1; build_scripts/20-packages.sh:1; build_scripts/desktop/install-desktop.sh:32–155; scripts/verify-manifest-packages.sh:1; scripts/verify-image-packages.sh:1; scripts/package-parity.sh:84–120. Add package contract projection and tests under tests/test_primary_packages.py (new). Preserve build-only/optional/excluded semantics; never flatten ordered operations into a set.

**Complexity:** High

**Token estimate:** ~35k tokens

**Agent strategy:** Parallel analysis, sequential integration.

### Phase 2.2: Transfer shared input and application policy

**File changes:** image-versions.yaml:1; registry-map.yaml:1; scripts/_registry.sh:1; scripts/resolve-image.sh:35–75; scripts/build-image-inner.sh:43–100; renovate.json:1; build_scripts/desktop/install-desktop.sh:1; tunaos.toml:1. Inventory Flatpak-bearing helpers before transferring their data; add scripts/lib/tunaos_inputs.py and tests/test_primary_inputs.py (new) if separation is warranted, while retaining one schema entrypoint.

**Complexity:** High

**Token estimate:** ~25k tokens

**Agent strategy:** Parallel analysis, sequential integration.

### Phase 3.1: Unify identity and artwork

**File changes:** build_scripts/90-image-info.sh:1–330; build_scripts/desktop/select-wallpaper.sh:1; build_scripts/lib/fork-branding.sh:1; scripts/prepare-fork-config.py:58–78; scripts/lib/tunaos_config.py:64; tunaos.toml:1. Reuse reviewed asset checks and add final-writer integration tests in tests/test_primary_branding.py (new); artwork remains referenced files, not embedded TOML data.

**Complexity:** High

**Token estimate:** ~25k tokens

**Agent strategy:** Parallel analysis, sequential integration.

### Phase 3.2: Share installer presentation

**File changes:** live-iso/common/src/customize-live.sh:1; scripts/build-iso-tacklebox.sh:1; scripts/build-iso-group.sh:1; scripts/prepare-fork-config.py:135–175; docs/PRIMARY-CONFIG-MIGRATION.md:1. Produce frontend-neutral payload and consumer contract tests in tests/test_primary_installer_branding.py (new). Frontend repositories are not modified by this phase without separately scoped work; verify the local projection and request bounded downstream changes if needed.

**Complexity:** High

**Token estimate:** ~25k tokens

**Agent strategy:** Parallel analysis, sequential integration.

### Phase 4.1: Build shared configuration authoring tools

**File changes:** scripts/config.py:10–30; scripts/lib/tunaos_config.py:1; scripts/check-package-sources.py:1; scripts/package-parity.sh:1; scripts/verify-manifest-packages.sh:1; scripts/check-package-repo-pins.py:1. Survey these existing mechanisms first; introduce native query adapters and a verified mapping catalog in scripts/lib/ only as needed. Add tests/test_primary_config_editor.py and tests/fixtures/primary-config/package-metadata/ (new). Evaluate tomlkit 0.13.3 as comment-preserving writer, reparse all output with the shared TOML 1.0 core. No automatic Gentoo category guess; disabled/held cells are reported and excluded from enabled-target resolution.

**Complexity:** High

**Token estimate:** ~35k tokens

**Agent strategy:** Parallel analysis, sequential integration.

### Phase 4.2: Retire legacy ownership and qualify delivery

**File changes:** docs/PRIMARY-CONFIG-MIGRATION.md:1; docs/rfc/rfc013-single-fork-config.md:1; docs/AGENT_GUIDE.md:1; docs/ci-troubleshooting.md:1; scripts/resolve-fork-config.py:1; scripts/prepare-fork-config.py:1; just/utilities.just:1; .github/green-criteria.yml:1; tests/test_ci_contract.py:1. Run just fix/check/test/ci as applicable and record actual results and blockers. Publish only through approved review/DCO process; no automatic merge. Preserve original PR3445 artifacts and receipts.

**Complexity:** High

**Token estimate:** ~25k tokens

**Agent strategy:** Parallel analysis, sequential integration.

## Testing Strategy

- 1.1: tests/test_primary_config.py compares the full captured matrix including object/list ordering and the acceptance-only Bonito profile.
- 1.2: core negative/mutation/atomic/symlink tests; shell fixtures; direct workflow preparation checks; receipt/copy-context integration; source-only Renovate match. Run both real parsers and native Python3.10 when available.
- 2.1: full resolved operation sequence parity for every supported native family; shared installer/verifier contract; excluded/optional/build-only and hold tests.
- 2.2: every writer updates its owning entry and all generated consumers reflect mutations; pins and mirror/application defaults remain equal.
- 3.1: safe asset path tests plus stock/custom identity, wallpaper precedence and final-writer checks in built images.
- 3.2: frontend-neutral payload tests, representative frontend screenshots and real-install checks; frozen historical receipts stay unchanged.
- 4.1: package metadata fixtures across versions/arches/repos, measured native aliases, unavailable/ambiguous cases, no partial edits, comment preservation and idempotence. htop is a test intent, not a production addition.
- 4.2: just fix, just check, just test and just ci as applicable, then existing build/boot/install gates. Record actual commands, output and limitations; never disable checks.

## Project References

- ../../../docs/PRIMARY-CONFIG-MIGRATION.md: ownership inventory, compatibility and full CLI requirements.
- ../../specs/20261020031206-primary-tunaos-toml-configuration.md: controlling user-facing requirements.
- ../../../AGENTS.md and ../../../docs/AGENT_GUIDE.md: mandatory project gates and no-person procedure.
- ../../../.github/runs-on.yml: Ubuntu24 custom runner images; hosted workflows use latest/24.04 and the manifest container installs Python explicitly.

## Token Management Strategy

| Tier | Token budget | Agent strategy |
|---|---|---|
| Low | ~10k | Single agent, sequential |
| Medium | ~25k | 2–3 independent workers |
| High | ~50k+ | Parallel analysis, sequential integration |

Split consumers by file ownership to avoid concurrent edits. Keep the shared core and integration owner singular. Read phase-specific context and exact source before editing; line numbers refer to the audit snapshot and may move.

## Migration Notes

This change implements the bounded matrix milestone only. Later milestones are planned, not authorized as unbounded current execution. RFC acceptance, publication and merging remain separate. Every procedural confirmation in this planning continuation is agent-supplied under AGENTS.md’s no-person rule, not represented as a human review.

Generated adapters are ignored and recreated after checkout/context copy. Retire the old authoritative source only once writers, runtime readers and tests have equivalent paths. Existing PR3445 qualification artifacts are never repinned. Unsupported future sections fail closed until their full consumer exists.

## Performance Considerations

Parse the small configuration on the authoring/build host; target images consume generated formats without TOML dependencies. Avoid rewriting identical adapters and avoid network access during parsing. Native package searches can cache metadata only with visible source/freshness and correct version/architecture keys; no performance target may weaken correctness or admission checks.
