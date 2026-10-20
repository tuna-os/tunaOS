---
created_date: "2026-10-20"
document_status: draft
---

# Plan: 20261020031206-primary-tunaos-toml-configuration

<!-- Created: 2026-10-20T03:33:12Z -->
<!-- Commit: 83362754 -->
<!-- Branch: refactor/primary-tunaos-config -->
<!-- Repository: https://github.com/tuna-os/tunaOS.git -->

## Overview

Give TunaOS and its customizers one readable product configuration for variants, packages and branding. Move ownership in verified stages so people can change defaults without a separate stock-only catalog, then add shared inspection and package-editing tools. Only the matrix milestone is approved for current implementation; the full requirement remains tracked.

## Conventions

- Regenerate derived outputs from their owner; source authority moves to TOML and never exists in two editable catalogs. This deliberately updates the old YAML owner named by the generated-files convention.
- Keep shell orchestration and Python parsing separate; retain yq for existing YAML consumers and use one strict TOML parser adapter.
- Test applied consumer behavior, including final branding writers; source equality alone does not qualify a built image.
- Use bats, pytest and the mandatory just gates, not Spektacular’s generic Go examples.
- Preserve external tool pin floors/ceilings and one owning entry. Shared pins remain in their current owner until milestone 2 transfers both writers and readers.
- Do not weaken a gate to pass; update declared gate contracts when jobs change.
- Refresh main before publication, record measured evidence and add useful troubleshooting guidance with the implementation.

Procedural convention review is agent self-confirmed under AGENTS.md’s no-person rule; this is not human RFC acceptance.

## Architecture & Design Decisions

The root TOML is the single editable product configuration for both TunaOS and people customizing it. One strict parser and resolver emit compatible machine formats for existing build and installer consumers. The matrix moves first; package policy, pins, identity, installer presentation and authoring tools retain explicit later milestones rather than becoming unconsumed fields.

The old matrix path becomes an ignored runtime adapter. Local readers use a shared resolution seam, workflow readers prepare the adapter after checkout, and copied contexts regenerate it after source-receipt verification. Invalid source fails before mutation and never falls back to stale stock data. This follows the generated-files convention while moving its authoritative input.

Dependency automation updates owning TOML entries only. No privileged regeneration bot or second committed matrix is required. Package and branding transitions preserve ordered operations and final-writer effects before old authorities are retired. See [rejected alternatives](./research.md#alternatives-considered-and-rejected) for the reasons not to rename the old fork overlay or rewrite all build engines at once.

The authoring interface shares the build schema and resolver. A comment-preserving edit layer must reparse its output through the same TOML 1.0 core. Native package queries report verified base/version/architecture/repository evidence and never treat a metadata hit as proof that a transaction will succeed.

## Component Breakdown

- Primary configuration core: owns syntax, strict schema, deterministic resolution and adapter generation; used by all entrypoints.
- Runtime preparation and compatibility seams: prepare derived formats for shell, Python, workflow and copied-context consumers while preserving explicit fixture overrides.
- Source receipts and dependency writers: attest only authoritative source and update each pin at its owner.
- Package contract resolver: preserves ordered native operations, repositories and admission constraints; feeds installation and verification together.
- Identity and installer projector: resolves safe referenced artwork and one versioned shared presentation payload, including final writers.
- Authoring interface: inspects provenance, searches configured repositories and previews atomic comment-preserving edits over the shared core.
- Validation evidence: golden, mutation, negative, integration and artifact tests establish each ownership transfer separately.

## Data Structures & Interfaces

The initial schema has integer schema_version=1, build.global_platforms, ordered iso_groups and sibling_images arrays, keyed tuna_rollout and variants tables, and ordered per-variant flavor arrays. Flavor fields preserve stage, platforms, build_image, build_iso, build_qcow2 and luks_e2e, including omission rather than invented defaults.

The matrix projection retains the old object shape: config, iso_groups, sibling_images, tuna_rollout, and an ordered variants array with explicit IDs. JSON serialization is a YAML-compatible adapter. The API is load(path) → validated configuration, matrix(config) → detached projection, render(config) → deterministic text, and prepare(root) → atomically refreshed adapter path.

Later typed contracts cover ordered package/repository operations, scoped identity, safe asset references and versioned installer presentation. General defaults, variants, desktops and exact cells have explicit scalar replacement and list replace/add/remove semantics. Query results include native name, base version, architecture, repository and freshness; editor results include a proposed diff and validation outcome. No arbitrary shell, remote include or secret values are permitted.

## Implementation Detail

Generate only after complete source validation, write a temporary file beside the destination, flush it and replace atomically. Identical content is a no-op; symlink and non-file targets are refused. Failure leaves the previous adapter intact but does not authorize consuming it.

Transfer ownership one contract at a time: record the old contract, project from TOML, compare behavior, migrate readers and writers, then retire the old source. Explicit fixture overrides are compatibility inputs, not a hidden production catalog. Receipt-based prepared contexts copy reviewed source and create the ignored adapter afterward.

Follow the shell/Python boundary and applied-effect conventions. Package generation must preserve ordered operations and admission holds; image and installer branding checks must include the last writer. The CLI layers comment-preserving editing over the same validator rather than defining a second schema.

## Dependencies

- Python 3.11+ tomllib provides the standard parser; Python 3.10 uses explicitly installed pinned tomli 2.2.1, with shared TOML 1.0 fixtures and no runtime downloads.
- Existing yq/jq and PyYAML readers retain their machine-format contract; workflow preparation needs Python on the runner, including Wolfi.
- The reviewed package installer, verifier, source receipt and branding mechanisms remain reusable consumers; their authority changes in stages.
- Utah’s grouped TOML package contract informs readable lists and shared installation/verification, but its separate overlay authority is not adopted.
- tomlkit 0.13.3 is the chosen editor candidate for later comment-preserving authoring; adoption requires shared-parser roundtrip and dependency-pin review.
- RFC 013, the primary configuration spec and delivery epic #3474 track the architectural transition; normal RFC/ADR and review gates remain independent of procedural self-confirmation.

## Testing Approach

Unit and golden tests establish complete value and ordering equality, strict unknown/type/duplicate rejection and deterministic atomic generation. Mutation tests prove that the owning source changes actual consumer inputs; stale generated files cannot hide invalid source. Integration tests cover local entrypoints, fresh checkout workflows, explicit fixtures and disposable source-receipt contexts.

Later milestones compare complete native package/repository operation sequences and validate final image/installer writers. Editor tests use contextual native metadata fixtures, ambiguous and unavailable mappings, idempotence and comment-preserving diffs. Both parser implementations must agree; native Python 3.10 execution remains a separate verification obligation.

Required project gates remain mandatory. Built-image, boot and real-install evidence is reported separately from source checks; no unchanged defaults claim substitutes for artifact qualification.

### Success metric to validation map

| Spec success metric | Validation and completion boundary |
|---|---|
| One authoritative editable product configuration | Inventory every retired owner and writer; fresh-checkout integration for each adapter; complete only after milestones 1–4. |
| No accepted but ignored field | Strict unknown-field tests plus mutation-to-final-consumer tests for every supported section. |
| No default input changes during ownership transfer | Full matrix/order golden, complete ordered package/repository parity, identity/asset-byte parity, then representative artifact gates. |
| Reproducible output and actionable errors | Repeated generation/no-op assertions, parser agreement, field-specific negative tests, atomic failure and symlink tests. |

## Milestones & Phases

### Milestone 1: Primary matrix authority

**What changes**: Complete matrix defaults move to TOML and every runtime reader derives its adapter safely. This is the only bounded implementation currently approved.

#### - [ ] Phase 1.1: Capture complete matrix ownership
**Repo:** tunaos

Move the complete current matrix into readable primary TOML without changing defaults. Preserve evidence of the old values so changes to source ownership can be distinguished from product changes.

*Technical detail:* [context.md#phase-11](./context.md#phase-11-capture-complete-matrix-ownership)

**Acceptance criteria**:
- [ ] Every default matrix value and variant/flavor ordering matches the recorded baseline.
- [ ] The ARM64-only Bonito acceptance profile is expressible without enabling it in production.


#### - [ ] Phase 1.2: Generate and consume the matrix safely
**Repo:** tunaos

Make local entrypoints and checked-out build jobs derive their matrix from the primary file. Keep the old machine-readable shape as an ignored adapter and refuse invalid source rather than reusing stale defaults.

*Technical detail:* [context.md#phase-12](./context.md#phase-12-generate-and-consume-the-matrix-safely)

**Acceptance criteria**:
- [ ] Fresh checkouts prepare the adapter before every real reader, including copied build contexts.
- [ ] Source changes reach consumers and invalid source leaves existing outputs untouched.
- [ ] Dependency updates change the authoritative base pin once and do not require committing an adapter.


### Milestone 2: Complete package and input authority

**What changes**: Ordered native package, repository, shared pin, mirror and application policy become owned by the same primary source.

#### - [ ] Phase 2.1: Move native package and repository policy
**Repo:** tunaos

Transfer desktop, shared and base-family package choices into readable typed TOML sections. Keep installation mechanisms as code and preserve native package names, ordering, exclusions and repository policy.

*Technical detail:* [context.md#phase-21](./context.md#phase-21-move-native-package-and-repository-policy)

**Acceptance criteria**:
- [ ] Every supported cell has the same ordered package and repository operations before and after migration.
- [ ] No accepted package section is ignored and no separate stock-only package list remains authoritative.
- [ ] Existing admission holds remain enforced.


#### - [ ] Phase 2.2: Transfer shared input and application policy
**Repo:** tunaos

Move shared image/tool pins, mirrors and application selections at the same boundary as their writers and consumers. Generate compatibility formats so the migration does not require replacing existing installation engines.

*Technical detail:* [context.md#phase-22](./context.md#phase-22-transfer-shared-input-and-application-policy)

**Acceptance criteria**:
- [ ] Each version or digest has one authoritative owner and automated updates edit that owner.
- [ ] Mirror, Flatpak and repository policy changes reach their intended consumers.
- [ ] Generated inputs preserve existing defaults with no hidden fallback.


### Milestone 3: Shared identity and installer presentation

**What changes**: Image and installer final writers consume the same resolved identity and safe referenced artwork.

#### - [ ] Phase 3.1: Unify identity and artwork
**Repo:** tunaos

Make stock and customized identity use the same resolved configuration. Preserve existing desktop and variant artwork precedence and validate local asset references before any build mutation.

*Technical detail:* [context.md#phase-31](./context.md#phase-31-unify-identity-and-artwork)

**Acceptance criteria**:
- [ ] Default identity and selected asset bytes are unchanged.
- [ ] Changes to names, URLs, emoji, logo and wallpaper reach final image writers.
- [ ] Escaping, absolute, missing or unsafe asset references are rejected.


#### - [ ] Phase 3.2: Share installer presentation
**Repo:** tunaos

Project one versioned branding payload for every installer frontend. Retire frontend-specific stock defaults only when each frontend demonstrably consumes the same resolved contract.

*Technical detail:* [context.md#phase-32](./context.md#phase-32-share-installer-presentation)

**Acceptance criteria**:
- [ ] Every supported installer frontend displays the intended name and assets.
- [ ] Stock and customized installer paths use the same payload.
- [ ] Existing frozen qualification evidence remains bound to its original source receipt.


### Milestone 4: Authoring and qualified delivery

**What changes**: Contextual package search, comment-preserving edits and explicit legacy migration share the build resolver. Full delivery requires built-image and real-install proof.

#### - [ ] Phase 4.1: Build shared configuration authoring tools
**Repo:** tunaos

Provide inspection, contextual package search and reviewable edits over the same schema used by builds. Resolve generic package intent using measured native mappings and preserve comments and unrelated formatting.

*Technical detail:* [context.md#phase-41](./context.md#phase-41-build-shared-configuration-authoring-tools)

**Acceptance criteria**:
- [ ] Adding htop resolves all configured supported base/version/architecture/repository cells, or reports ambiguity without a partial edit.
- [ ] Repeated additions are a no-op and proposed changes are reviewable before writing.
- [ ] Search results distinguish metadata availability from transaction solvability.
- [ ] Hand editing and CLI editing use the same validator and resolver.


#### - [ ] Phase 4.2: Retire legacy ownership and qualify delivery
**Repo:** tunaos

Document the primary interface and explicit migration route from legacy preview configurations. Qualify representative images and real installations before declaring the full package and branding goal complete.

*Technical detail:* [context.md#phase-42](./context.md#phase-42-retire-legacy-ownership-and-qualify-delivery)

**Acceptance criteria**:
- [ ] Legacy authoritative sources are retired only after equivalent consumers and writers are in place.
- [ ] Required formatting, regression and contract gates pass without weakened assertions.
- [ ] Built-artifact and real-install results are recorded separately from source parity.
- [ ] The full user goal remains open until package, identity, installer and authoring acceptance is met.

## Open Questions

No unresolved design question blocks the approved matrix milestone. Later native package availability and transaction behavior must be measured against each configured repository at implementation time. If a required mapping is absent or ambiguous, stop that edit and report the affected base/version/architecture; do not invent a mapping or partially apply it. Artifact qualification outcomes remain unknown until builds and real installs run; failures block delivery rather than changing acceptance.

## Out of Scope

- No hardware support, desktop version or admission-policy changes. The Bonito ARM64 profile is an acceptance fixture, not production enablement.
- No automatic publication, merge, credential management or host package installation as a side effect of authoring or search.
- No guessed cross-distribution package mappings, arbitrary executable configuration or on-demand dependency downloads.
- No modification or repinning of existing PR3445 frozen image and installer qualification evidence.
- No claim that the previous fork-only preview or the current matrix milestone completes primary configuration ownership.
- Package/input migration, branding/installer migration and the authoring CLI are outside the currently approved implementation slice; they remain explicit milestones 2–4 in this plan and delivery epic #3474.
