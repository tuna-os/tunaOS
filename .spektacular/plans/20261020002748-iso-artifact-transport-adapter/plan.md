---
created_date: "2026-10-20"
document_status: final
closed_date: "2026-10-20"
---

# Plan: 20261020002748-iso-artifact-transport-adapter

<!-- Created: 2026-10-20T00:33:38.758896+00:00 -->
<!-- Commit: ec5faa12 -->
<!-- Branch: rfc014-artifact-adapter -->
<!-- Repository: tuna-os/tunaOS -->

## Overview

Verify selected producer artifact snapshots without enabling production qualification. Maintainers gain explicit rejection tests and a documented boundary for later authenticated collection.

## Conventions

- **Main is canonical** — develop on merged RFC014 and recheck main before publication.
- **Evidence style** — distinguish synthetic checks from authenticated production evidence.
- **Behavioral tests** — fake transport and counted streams execute rejection behavior.
- **Fix and check before commit** — run mandatory formatting and validation.
- **Troubleshooting diagnosis** — document the artifact upload-attempt API gap.

## Architecture & Design Decisions

Implement a standard-library Python module in tunaos, with immutable reviewed policy and explicit selection inputs. An injected transport offers JSON GET and a bounded binary stream; the adapter constructs only exact repository/run/attempt/artifact endpoints. It never accepts candidate URLs, lists runs or extracts archives. Return conditional snapshot checks and measured archive identity with authentication not_authenticated.

Require successful workflow_dispatch on main, same repository ID/name, exact workflow ID/path and reviewed source SHA. Read the current run, selected attempt and artifact metadata before opening archive bytes. Hash the stream within independent limits, then re-read current run. Every run snapshot must remain attempt1 and agree on identities. Any unsupported rerun or missing linkage rejects. The adapter does not manufacture RFC014's native producer or a complete observed-transport document.

Compared with a network-aware collector, dependency injection leaves credentials and freshness enforcement outside this stage. Compared with arbitrary snapshots, ordered calls make the race policy executable and testable. Full extraction is deferred to avoid combining archive security and producer migration with this bounded phase. See research.md#alternatives-considered-and-rejected. Behavioral tests follow the project's pytest and evidence conventions; no gates are weakened.

## Component Breakdown

- Reviewed policy and explicit selection hold immutable caller-provided coordinates and limits.
- Snapshot verifier validates only consumed API fields and rejects unsupported attempts and identities before archive access.
- Archive hasher streams a bounded binary input and compares its measured digest with independent policy and API metadata.
- Fake transport tests enforce exact read sequence, error paths and absence of network/writes.
- RFC/ADR and troubleshooting documentation record scope approval and the API limitation.

## Data Structures & Interfaces

- `ReviewedPolicy`: frozen repository ID/name, workflow ID/path, source SHA, branch, expected archive digest and maximum archive bytes. Policy is independently reviewed input, never candidate receipt data.
- `ArtifactSelection`: frozen positive run ID, attempt and artifact ID; only attempt1 is supported.
- `ReadOnlyTransport`: `get_json(path)` returns parsed API data; `open_archive(path)` returns a context-managed binary stream. Future implementations must use fresh authoritative API responses and safe redirect handling.
- `verify_artifact_snapshot(policy, selection, transport)`: returns checked coordinates and measured archive digest/size with explicit unauthenticated snapshot status, or raises a classified rejection. It returns neither a full RFC014 transport pair nor media qualification.

## Implementation Detail

The module keeps validation separate from ordered transport calls. It validates consumed API fields strictly while allowing unrelated GitHub response fields, and uses stable rejection codes. Cheap mismatches reject before archive reads. Bounded hashing compares both independent expected digest and API digest; streams close on all paths. A second run snapshot catches visible reruns. Output describes the conditional snapshot and leaves authentication explicit.

## Dependencies

- RFC014 offline contract, merged in #3485 — establishes identity/authentication separation; remains unchanged.
- Python standard library — hashing, immutable types and binary streams; no new runtime package.
- Existing pytest tooling — fake transport and behavioral tests.
- GitHub REST response contract — consumed via injected transport only; no live network client in this phase.
- Design documents this plan was built on: none registered; RFC014 and ADR0014 supply the approved boundary.

## Testing Approach

Use pytest behavioral tests with a deterministic fake transport and counted binary streams. Each consumed identity field is independently mutated or omitted, including boolean-for-integer cases. First-attempt policy tests cover attempt2 selection, rerun before collection and transition during collection. Exact request order proves no listing or receipt URL is used. Cheap rejection must read zero archive bytes; digest mismatch, truncated, oversized and invalid streams reject and close.

Every declared rejection requirement maps to a test. Successful output explicitly remains unauthenticated and lacks native or qualification fields. Existing offline contract tests run unchanged as compatibility coverage. Production authentication and runtime installation have no success claim in this phase; real proof stays open in the epic. Mandatory format/lint and CI contract tests remain enabled.

## Milestones & Phases

### Milestone 1: Reject mismatched producer evidence
Maintainers gain an offline-testable adapter that rejects unrelated, rerun or incomplete producer metadata before downloading archive bytes. This is internal groundwork with no production behavior change. Validation: metadata mutation tests and exact read-order checks pass.

### Milestone 2: Verify selected archive bytes honestly
Maintainers can verify archive content against independently selected and API-reported identity, with clear snapshot and authentication limits. Validation: bounded-stream adversarial tests, existing contract compatibility tests and repository gates pass; public documentation records the remaining integration work.

#### - [x] Phase 1.1: Bind explicit producer metadata
**Repo:** tunaos
Implement reviewed policy and explicit selection checks against read-only run and artifact observations. Reject missing linkage and unsupported reruns before archive access.
*Technical detail:* [context.md#phase-11](./context.md#phase-11-bind-explicit-producer-metadata)
**Acceptance criteria**:
- [x] Valid synthetic metadata passes and each identity mutation rejects.
- [x] No listing, latest selection or receipt-supplied URL is used.

#### - [x] Phase 2.1: Verify archive bytes and document limits
**Repo:** tunaos
Hash selected archive bytes within independent limits and recheck the run snapshot. Document the API race model and the remaining producer and authentication work.
*Technical detail:* [context.md#phase-21](./context.md#phase-21-verify-archive-bytes-and-document-limits)
**Acceptance criteria**:
- [x] Corrupt, truncated, oversized and invalid streams reject.
- [x] A visible rerun during collection rejects.
- [x] Output cannot claim authentication or qualification.
- [x] Existing contract tests and repository checks remain green.

## Open Questions

No implementation-only uncertainties remain. Missing or ambiguous API linkage rejects rather than changing the policy.

## Out of Scope

- Production caller, credentials or admission activation — later RFC014 integration under #3470.
- Browser/native v2 emitters and real installation proof — iso-builder#270 and tunaOS#3431.
- ZIP member extraction and receipt interpretation — later transport-to-media integration.
- Rerun authentication, signatures and provenance attestations — separate reviewed design; signing policy in #1187.
- Download routing or retained-object deletion — excluded from this phase.


## Changelog

### 2026-10-20 — Phase 1.1: Bind explicit producer metadata

**What was done**: Added strict reviewed-policy and selected-run/artifact metadata checks. Independent tests passed 362 cases; compilation and diff checks passed.

**Deviations**: None.

**Files changed**:
- `tunaos: scripts/iso_artifact_transport.py`
- `tunaos: tests/test_iso_artifact_transport.py`
- `tunaos: tests/fixtures/iso-artifact-transport-v1/case.json`

**Discoveries**: Repository ID equality and explicit fork flags are both checked, so contradictory snapshots reject. Artifact upload-attempt identity remains absent from the API; only the conservative first-attempt policy is supported.

### 2026-10-20 — Phase 2.1: Verify archive bytes and document limits

**What was done**: Added bounded exact-size/hash verification and fresh artifact/run checks after collection. Independent verification passed 562 adapter tests plus 502 unchanged contract/schema tests. Compilation and diff checks passed; mandatory format/lint checks passed with the unchanged STE budget.

**Deviations**: Official uploader source confirmed API size and uploaded archive bytes use the same measure. The adapter therefore enforces exact length, and rechecks artifact identity/expiry before the final run snapshot.

**Files changed**:
- `tunaos: scripts/iso_artifact_transport.py`
- `tunaos: tests/test_iso_artifact_transport.py`
- `tunaos: tests/fixtures/iso-artifact-transport-v1/case.json`
- `tunaos: docs/rfc/rfc014-iso-media-provenance.md`
- `tunaos: docs/adr/0014-iso-media-provenance-contract.md`
- `tunaos: docs/ci-troubleshooting.md`

**Discoveries**: The official uploader finalizes size and digest from uploaded bytes. The adapter still cannot authenticate its injected transport or reviewed-policy input, and never emits full native/browser qualification evidence.
