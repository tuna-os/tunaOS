---
created_date: "2026-10-20"
document_status: final
closed_date: "2026-10-20"
---

# Feature: 20261020002748-iso-artifact-transport-adapter

## Overview

Add a read-only evidence adapter that checks whether a selected build artifact matches a reviewed producer run. It gives maintainers explicit rejection reasons before any future qualification integration, without changing downloads or claiming installation success.

## Requirements

- [x] **Explicit selection**
  The adapter must reject unspecified producer runs and artifacts.
- [x] **Reviewed producer**
  The adapter must match independent reviewed repository, workflow, source and branch policy.
- [x] **Successful manual first attempt**
  The adapter must reject failed, incomplete, PR and rerun evidence, including a rerun observed during collection.
- [x] **Exact artifact bytes**
  The adapter must bind the selected artifact identity and archive bytes to the selected run and reject expired, malformed or mismatched evidence.
- [x] **Limited result**
  The adapter must distinguish a verified snapshot binding from producer authentication and runtime qualification.
- [x] **Fail closed**
  Missing API linkage must produce explicit rejection, never a receipt-derived replacement.

## Constraints

- The maintainer-approved phase is read-only and has no production caller.
- The approved producer scope is a successful manual iso-builder CI run on main at a reviewed source revision.
- RFC014 keeps independently obtained policy and transport separate from candidate receipts.
- GitHub artifact metadata does not expose an upload attempt; unsupported attempt binding must fail closed.
- Existing downloads, credentials and workflow permissions remain unchanged under the approved scope.
- The first adapter supports only a first-attempt snapshot; reruns remain unsupported.

## Acceptance Criteria

- [x] **Selected snapshot passes**
  A complete synthetic first-attempt manual-run snapshot with matching reviewed coordinates and exact archive bytes yields a limited binding result.
- [x] **Identity mutations reject**
  Changing repository, workflow, source, branch, run, attempt, artifact or archive bytes rejects the input.
- [x] **Unsafe evidence rejects**
  PR, fork, failed, incomplete, expired and rerun evidence cannot produce a successful result.
- [x] **No missing-data substitution**
  Absent or wrongly typed linkage rejects even when a receipt asserts the expected value.
- [x] **No authorization claim**
  Successful output cannot claim authenticated provenance or qualified media.

## Technical Approach

- Prefer an injected read-only transport so unit tests can exercise official API response shapes without credentials or network activity.

## Success Metrics

- Every declared rejection case is covered by an executable test.
- No real production qualification or installation success is inferred from synthetic fixture results.

## Non-Goals

- Browser and native v2 receipt emitters remain separate work.
- Actual offline plain/encrypted installation and target-only reboot remain separate proof.
- Artifact extraction and receipt interpretation remain outside this metadata-and-archive binding adapter.
