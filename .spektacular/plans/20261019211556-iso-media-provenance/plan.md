---
created_date: "2026-10-19"
document_status: final
closed_date: "2026-10-19"
---

# Plan: 20261019211556-iso-media-provenance

Created: 2026-10-19T21:29:48Z
Commit: e6f1a092
Branch: rfc014-iso-media-provenance
Repository: tuna-os/tunaOS

## Overview

Establish a versioned contract for the exact media and software identities behind browser-built installation tests. Maintainers gain repeatable checks for ambiguous or mismatched evidence before production integration.

## Conventions

- **Main is canonical** — build the pure foundation on current main, without pending #3431 infrastructure.
- **Check main before publication** — reconcile concurrent changes before the PR.
- **Assert applied behavior** — execute validators against changed bytes and hostile claims.
- **Never weaken gates** — missing evidence remains rejected and runtime acceptance remains open.
- **Evidence style** — report exact tests and distinguish consistency from authentication.
- **Fix and check before commit** — run the mandatory format and lint commands.
- **Bats/pytest/just** — Python tests follow the repository framework; no Go test defaults.
- **STE prose budget** — keep new RFC and ADR text within the existing ratchet.

## Architecture & Design Decisions

Add an offline Python contract module, a versioned JSON schema and language-neutral vectors in tunaos. Keep the module independent of pending #3431. The module separates document validation, exact-byte digest checks and comparison with independently supplied expected context. It returns conformance results only, never a qualified catalog entry. This follows the main-is-canonical and never-skip-a-gate conventions.

The browser and native roles retain their existing kind vocabulary with explicit v2 dispatch. Typed source, overlay, frontend, builder and harness descriptors prevent role substitution. Final ISO identity lives in external receipts; uploaded artifact identity lives in separate context. Legacy documents have a distinct diagnostic path. Content hashes prove byte identity, not producer authority. Resource records identify their subject, quantity, unit, source and method.

Use standard-library validation plus a declarative schema: the runtime stays dependency-light while schema tests provide a separate structural oracle. Python tests follow the existing importlib pattern; shared vectors permit later JavaScript and native adapters. Do not add those production integrations in this stage. Evidence-style and applied-state conventions require actual validator outputs, rather than assertions that files exist. See research.md#alternatives-considered-and-rejected for the rejected v1 extension and pending-infrastructure import.

## Component Breakdown

- **Version dispatcher** identifies supported browser and native v2 roles and keeps recognized legacy documents diagnostic-only.
- **Structural validator** checks closed fields, typed identities, browser profile and resource observations against the contract.
- **Binding validator** compares exact media and receipt bytes plus independently supplied expected identities and producer context. It does not fetch or authenticate that context.
- **Conformance vectors** give producers and consumers common positive and adversarial cases, with distinct identities for each role and tiny media bytes.
- **Governance documents** record the approved boundary, migration, later integration obligations and unchanged production policy.

## Data Structures & Interfaces

- **BrowserEvidenceV2** binds final media to typed input descriptors, exact build inputs, a browser profile, resource observations and declared producer coordinates.
- **NativeEvidenceV2** binds native test observations to that media and the exact browser receipt, with separate harness and QEMU identities. Plain and encrypted results remain separate.
- **ExpectedContextV2** supplies independently verified producer coordinates, reviewed workflow/source identities, artifact archive identity and expected input descriptors. It is an argument, never an embedded authorization claim.
- **ConformanceResult** reports structural and binding success without a production-qualified flag. Legacy reading reports diagnostic-only status.
- **Interfaces**: strict JSON parsing; validate one document; compare browser/native documents and media bytes with expected context; inspect recognized legacy metadata without admission.

## Implementation Detail

Introduce a narrow pure module with explicit trust-boundary names. Parsing rejects duplicate keys and non-finite JSON. Structural errors and identity mismatches produce deterministic field-level diagnostics. Legacy inspection cannot call the v2 binding path implicitly.

Tiny deterministic media bytes and distinct digest values expose identity swaps. Shared vectors keep the contract portable; schema tests and behavioral tests exercise different layers. Existing production catalog, report and publication workflow code remains unchanged, so no fixture can become production evidence through this PR.

## Dependencies

- Python standard library supplies parsing, hashing and validation; no new runtime package.
- Existing pytest supplies behavioral checks. Add explicit jsonschema development dependency setup for the independent schema oracle; no runtime import.
- Design documents this plan was built on: none in the registered design store. The approved public proposal in iso-builder#270 comment6277123450 defines the bounded approach.
- RFC lifecycle and the current ISO media spec govern this work; the bounded maintainer approval is recorded in tunaOS#3381 comment6277491364.
- Pending #3431 is an integration reference, not a required merge prerequisite for this isolated module. Its later adapters require their own reconciliation and review.
- Existing iso-builder browser receipts and tunaOS#1187 signing policy remain future integration dependencies; neither changes in this stage.

## Testing Approach

Use behavioral contract tests and an independent schema oracle over shared vectors. Positive cases use distinct identities and tiny real bytes. Negative cases mutate bytes, role kinds, versions, platforms, producer coordinates and resource provenance. Recomputed receipt checksums cannot overcome an expected-context mismatch.

The highest coverage belongs to strict parsing and cross-document binding: duplicate keys, booleans as numbers, non-finite values, unknown fields, legacy dispatch, changed ISO size/hash, wrong workflow/source/run/attempt/artifact and frontend/builder substitutions must fail. Missing or failed plain/encrypted observations must not pass the native contract.

The spec's success metric is checked by repeatable acceptance-suite execution; report exact vector results as the baseline for later adapter reviews. Production policy preservation is checked by the scoped diff and absence of production call sites. Actual authenticated collection, browser execution and VM installation remain deliberate integration gaps, not simulated successes.

## Milestones & Phases

### Milestone 1: A reviewable media identity contract
Maintainers can distinguish source, overlay, installer, builder, final media and test harness identities. The versioned contract records legacy treatment and the approved trust boundary. Validation: schema, RFC and bounded ADR agree with the approved proposal.

#### - [x] Phase 1.1: Define the typed media contract
**Repo:** tunaos

Record the approved versioned identity contract and compatibility boundary. Give reviewers a schema and decision record that distinguish every identity role and keep old evidence diagnostic-only.

*Technical detail:* [context.md#phase-11](./context.md#phase-11-define-the-typed-media-contract)

**Acceptance criteria**:
- [x] Source, overlay, frontend, builder, final media and harness have distinct typed identities.
- [x] Legacy handling and independent producer authorization boundaries are explicit.
- [x] The recorded approval covers only the contract stage.

### Milestone 2: Repeatable rejection of mismatched evidence
Contributors can check candidate browser/native evidence against exact bytes and independently supplied expectations. This internal foundation prevents ambiguous identities without changing downloads. Validation: shared positive and hostile vectors pass the acceptance suite, with no production admission call site.

#### - [x] Phase 2.1: Validate evidence without production activation
**Repo:** tunaos

Add an offline consistency checker and common test cases. Exact bytes and expected context determine whether evidence conforms; receipt claims alone cannot override expectations. Downloads and production qualification stay unchanged.

*Technical detail:* [context.md#phase-21](./context.md#phase-21-validate-evidence-without-production-activation)

**Acceptance criteria**:
- [x] Conforming browser/native pairs pass structural and binding checks.
- [x] Changed media, substituted identities and unapproved producer coordinates fail.
- [x] Invalid JSON, legacy input and misleading resources cannot pass v2 checks.
- [x] No production consumer or publication policy uses synthetic fixtures or this checker.

## Open Questions

No implementation-time-only questions remain for the bounded offline contract. Authentication and real-media execution belong to later integration work.

## Out of Scope

- Production collector activation, browser-qualified labels and delivery cutover remain in iso-builder#270 and tunaOS#3470/#3381.
- Real browser builds, offline plain/encrypted installation and target-only reboot remain required runtime acceptance work.
- Artifact retention changes, object deletion, new publication streams, credentials and workflow permission expansion are excluded.
- Existing signing policy remains under tunaOS#1187; a hash match is not an attestation.
- Pending #3431 adapters and builder JavaScript/native consumer integration require separate review after this contract stage.

## Changelog

### 2026-10-19 — Phase 1.1: Define the typed media contract

**What was done**: Added the v2 structural schema, RFC014, bounded ADR0014 and portable synthetic fixtures. Independent verification passed 179 schema tests and the aggregate check on the explicit formatting dependency.

**Deviations**: Separate PR3483 fixes a pre-existing two-tab shfmt failure. This branch temporarily depends on that repair; no gate was waived.

**Files changed**:
- tunaos: schemas/iso-media-provenance-v2.schema.json
- tunaos: docs/rfc/rfc014-iso-media-provenance.md
- tunaos: docs/rfc/README.md
- tunaos: docs/adr/0014-iso-media-provenance-contract.md
- tunaos: docs/adr/README.md
- tunaos: tests/test_iso_media_schema.py
- tunaos: tests/fixtures/iso-media-provenance-v2/schema-browser.json
- tunaos: tests/fixtures/iso-media-provenance-v2/schema-native.json
- tunaos: tests/fixtures/iso-media-provenance-v2/schema-context.json
- tunaos: tests/fixtures/iso-media-provenance-v2/schema-transport.json

**Discoveries**: Observed transport metadata needs a separate input because archive identity is assigned after receipt creation. The schema validates structure only; phase 2 checks consistency with expected context.

### 2026-10-19 — Phase 2.1: Validate evidence without production activation

**What was done**: Added the offline consistency checker, shared exact-byte vectors and hostile-input tests. Separate expected and observed transport inputs preserve the authentication boundary. Fresh verification passed 441 schema and behavioral tests, 99 fork-config and CI-contract tests, schema self-validation, format/lint and production-call-site inspection.

**Deviations**: The first integration command omitted the configured yq PATH and failed one test; its corrected invocation passed all 99. No acceptance gate was waived. Separate PR3483 remains the temporary formatter dependency.

**Files changed**:
- tunaos: scripts/iso_media_provenance.py
- tunaos: schemas/iso-media-provenance-v2.schema.json
- tunaos: tests/test_iso_media_provenance.py
- tunaos: tests/test_iso_media_schema.py
- tunaos: tests/fixtures/iso-media-provenance-v2/cases.json
- tunaos: tests/fixtures/iso-media-provenance-v2/media.bin
- tunaos: tests/fixtures/iso-media-provenance-v2/schema-browser.json
- tunaos: .github/workflows/test.yml
- tunaos: just/utilities.just
- tunaos: image-versions.yaml
- tunaos: docs/rfc/rfc014-iso-media-provenance.md

**Discoveries**: JSON exponent overflow needs a finite-float parser in addition to rejection of literal non-finite tokens. Stream reads need an independent size bound. Resource observations need source/method pairing. These checks establish consistency only; authenticated collection and actual matching-media installation remain open.
