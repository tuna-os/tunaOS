---
created_date: "2026-10-20"
document_status: final
closed_date: "2026-10-20"
---

# Research: 20261020002748-iso-artifact-transport-adapter

## Alternatives considered and rejected
- Receipt-asserted attempt or timestamp inference: GitHub artifact metadata lacks upload-attempt identity; assertions cannot establish it.
- Full ZIP extraction and native pairing now: exceeds this metadata/archive adapter and requires separately reviewed extraction limits and producer adapters.
- Latest successful run selection: conflicts with explicit approved selection and reviewed source policy.

## Chosen approach — evidence
Injected read-only transport with explicit coordinates and a conservative first-attempt snapshot policy. Current run, attempt endpoint and artifact linkage must match. A second current-run snapshot after bounded archive hashing must remain completed-success attempt1. The result reports checks conditional on trustworthy transport, never authentication.

## Files examined
- tunaos:scripts/iso_media_provenance.py:200 — full observed transport includes both producers and receipt paths; this browser-only phase must not fabricate it.
- tunaos:tests/test_iso_media_provenance.py:12 — importlib/pytest and counting-stream fixtures.
- iso-builder:e2e/tests/builder.spec.js:581 — existing v1 emitter lacks final media identity.
- iso-builder:.github/workflows/ci.yml:607 — legacy native harness pinned separately; no v2 inference allowed.
- tunaos:docs/adr/0014-iso-media-provenance-contract.md:21 — later adapters require review.

## External references
- https://docs.github.com/en/rest/actions/artifacts#get-an-artifact — artifact workflow_run identifies run, repository and head, not upload attempt.
- https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run-attempt — attempt-scoped run observations.
- https://github.com/actions/upload-artifact#overwriting-an-artifact — replacement creates a new immutable artifact ID.

- https://github.com/actions/toolkit/blob/main/packages/artifact/src/internal/upload/upload-artifact.ts — finalized size and SHA256 both describe uploaded bytes; exact length equality is valid.

## Prior plans / specs consulted
- 20261019211556-iso-media-provenance/research.md via CLI — typed identity and no production caller boundary.
- Current spec via CLI; no registered design references.

## Open assumptions
Fresh authoritative API responses and independently reviewed policy must be supplied by a future caller. This module cannot establish either. REST snapshots are not atomic. Supporting reruns requires a separate trusted upload-attempt proof design.

## Drafting assumptions

### Injected transport and no extraction (architecture)
- **Decision**: Separate metadata/archive verification from authentication and member extraction.
- **Rationale**: Small reviewed phase, no new credentials or production caller.
- **Rejected**: Full collector would expand scope; raw snapshot-only API would hide collection order.
### First-attempt policy (architecture)
- **Decision**: Require before/after current-run attempt1 and matching attempt endpoint.
- **Rationale**: Artifact API omits upload-attempt linkage; explicit conservative restriction reviewed.
- **Rejected**: Receipt assertions and timestamps cannot independently prove reruns.

## Rehydration cues
Read RFC014, ADR0014, current spec and the official API references. Run the fake-transport and counted-stream tests before changing collection order.
