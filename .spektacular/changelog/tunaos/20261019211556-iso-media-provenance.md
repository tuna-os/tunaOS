---
created_date: "2026-10-19"
document_status: draft
project: tunaos
spec: 20261019211556-iso-media-provenance
plan: 20261019211556-iso-media-provenance
---

# ISO media provenance contract

TunaOS contributors can check whether browser and native installation evidence describes the same media and software. The offline checks reject mismatched bytes, ambiguous identity roles and unsupported claims. They do not authenticate producers or qualify downloads.

Derived from project tunaos, spec/plan 20261019211556-iso-media-provenance. See the project-level record for the full feature.

## What changed in tunaOS

RFC014 and ADR0014 record the approved bounded approach. A v2 schema separates source, overlay, deployed frontend, WASM builder, final media and native harness identities. A standard-library checker compares exact receipt and media bytes with separate expected context and observed transport. Legacy evidence stays diagnostic-only. Shared fixtures and 441 schema/behavioral tests cover valid and hostile inputs; 99 integration tests also passed. The independent schema test dependency is centrally pinned.

## Why

Distinct identities and exact-byte bindings give later producer and collector integrations a repeatable acceptance baseline. The authenticated collector and actual matching-media browser build, plain/encrypted offline installation and target-only reboot remain open work.

## Deviations

Separate PR3483 repairs a pre-existing two-tab formatter failure and is a temporary dependency. One integration invocation omitted the configured yq PATH; the corrected invocation passed all 99 tests. No acceptance gate was waived and no production admission caller was added.
