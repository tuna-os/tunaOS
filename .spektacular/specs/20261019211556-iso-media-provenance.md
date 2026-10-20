---
created_date: "2026-10-19"
document_status: final
closed_date: "2026-10-19"
---

# Feature: 20261019211556-iso-media-provenance

## Overview

Establish verifiable identity for browser-built installation media so users can
trust which image, installer and build engine were tested together. Keep old or
unbound results visible as diagnostics while withholding browser qualification
until the exact media passes the required installation and reboot checks.

## Requirements

- [x] **Exact media identity**
  The system must bind browser and native observations to the same final ISO bytes.
- [x] **Typed input identity**
  The system must distinguish source image, overlay, installer frontend, builder and test harness identities.
- [ ] **Independent trust**
  The system must independently verify evidence origin and producer authorization.
- [x] **Explicit resources**
  The system must distinguish measured, reported and estimated browser resources.
- [ ] **Shared conformance**
  Participating producers and consumers must agree whether evidence conforms to the contract.

## Constraints

- The approved [proposal](https://github.com/tuna-os/iso-builder/issues/270#issuecomment-6277123450) requires independently obtained CI artifact metadata and producer configuration reviewed by maintainers. Trusted configuration must pin the workflow definition and source revision. Receipt data and untrusted pull requests cannot authorize their own producer.
- Version 2 must distinguish the source OCI manifest and platform, overlay content, build-engine module, installer frontend deployed commit, optional installer bundle bytes, and native test harness. These roles cannot substitute for each other. Version 1 remains diagnostic-only; missing or unknown versions cannot pass admission.
- Producers and consumers must use shared positive and negative conformance fixtures.
- Existing downloads must remain available and unqualified targets must retain fallback delivery. Contract-stage changes cannot alter production qualification or publication decisions.
- Resource quantities must retain positive finite values, units and observation method. Supported initial quantities are memory capacity and available storage in bytes, and elapsed duration in seconds. Methods are measured, reported and estimated; browser deviceMemory and storage estimates cannot establish measured physical capacity. Missing or unknown required observations cannot pass admission.
- RFC-PROCESS.md requires a documented approach, tracking issue, maintainer approval and decision record.
- Existing browser/native evidence roles and release-signing policy must remain distinct from content-hash checks.

## Acceptance Criteria

- [x] **Media mismatch rejected**
  Changed ISO bytes or a mismatched browser/native media reference are rejected.
- [x] **Identity substitution rejected**
  A QEMU hash, backend binary hash or wrong source platform cannot replace the required builder, frontend or source identity.
- [ ] **Untrusted context rejected**
  A matching content hash from an unapproved workflow, source revision, run attempt or artifact is rejected.
- [x] **Legacy remains diagnostic**
  Version 1 receipts remain readable as diagnostics. Missing, unknown and version 1 receipts never produce a qualified result.
- [x] **Resource provenance retained**
  Accepted resource observations retain the supported quantity, method and unit. Unsupported, missing required, non-positive or non-finite values are rejected.
- [ ] **Participant agreement**
  Supported participants accept conforming evidence and reject nonconforming evidence consistently.
- [x] **Activation stays blocked**
  Production qualification status and download publication behavior remain unchanged after contract-stage delivery.

## Technical Approach

- Prefer a pure contract and shared fixture stage before connecting real producers and the trusted collector, so each trust boundary can be reviewed separately.

## Success Metrics

- Acceptance-suite completion supplies a repeatable baseline for the later producer and collector integration reviews.

## Non Goals

- The initial contract stage does not activate production collectors.
- It does not delete retained objects or create another ISO publication stream.
- It does not create credentials, expand workflow permissions or introduce a hosted build service.
- It does not replace the separate real browser-build, offline plain/encrypted installation, target-only reboot or paired performance acceptance work.
