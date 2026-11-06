---
created_date: "2026-10-20"
document_status: final
closed_date: "2026-10-20"
---

# Context: 20261020002748-iso-artifact-transport-adapter

## Current State Analysis

RFC014 landed at ec5faa12. Its checker accepts independent context but authenticates nothing. No production caller is added.

## Per-Phase Technical Notes

### Phase 1.1: Bind explicit producer metadata
- Files: new scripts/iso_artifact_transport.py and tests/test_iso_artifact_transport.py; test-only fixture tests/fixtures/iso-artifact-transport-v1/case.json.
- Policy: repository tuna-os/iso-builder (ID1305022978), workflow ID315782939/path.github/workflows/ci.yml, refs/heads/main, reviewed source fc0b1375ac61b1180add8469db702a083709b844. IDs verified from public repo and run39321317858; that push run is not admissible manual evidence.
- Implement frozen ReviewedPolicy(repository, repository_id, workflow_id, workflow_path, source_revision, ref, archive_sha256, max_archive_bytes), ArtifactSelection(run_id, attempt, artifact_id), and verify_artifact_snapshot(policy, selection, transport).
- ReadOnlyTransport.get_json(relative_path) and open_archive(relative_path) are injected; exact endpoint construction only. Validate current run, attempt endpoint and artifact workflow_run linkage; reject unknown consumed fields, bool IDs, missing objects, PR/fork, wrong source or unsuccessful state.
- Complexity: Medium. Token estimate: ~5k. Agent strategy: primary implementation, independent negative-test review.

### Phase 2.1: Verify archive bytes and document limits
- Files: scripts/iso_artifact_transport.py, tests/test_iso_artifact_transport.py, docs/rfc/rfc014-iso-media-provenance.md, docs/adr/0014-iso-media-provenance-contract.md and docs/ci-troubleshooting.md.
- Stream max1MiB reads, independently bounded archive bytes, exact SHA256 against policy and API digest. Official actions/toolkit upload-artifact.ts finalizes size from actual uploaded bytes; require exact streamed length == API size_in_bytes as well as the independent cap. Stream must begin at zero when seekable. Re-fetch artifact metadata after hashing, require unchanged size/digest/linkage and nonexpired state, then re-read current run. Return metadata_checks_passed, archive_digest_verified, attempt_policy:first_attempt_only, authentication:not_authenticated and measured coordinates/digest/size. Never nativeProducer or qualified.
- Context-managed stream closes on failure. Transport exceptions propagate and never produce success. No extraction or disk output.
- Tests include exact call sequence, all consumed field omissions/type mismatches, wrong archive digest, bounded extra-byte rejection and before/after rerun race. Existing 502 contract/schema tests run unchanged.
- Complexity: Medium. Token estimate: ~5k. Agent strategy: independent tests and review, sequential integration.

## Testing Strategy

Use pytest behavioral tests with a deterministic fake transport and counted binary streams. Each consumed identity field is independently mutated or omitted, including boolean-for-integer cases. First-attempt policy tests cover attempt2 selection, rerun before collection and transition during collection. Exact request order proves no listing or receipt URL is used. Cheap rejection must read zero archive bytes; digest mismatch, truncated, oversized and invalid streams reject and close.

Every declared rejection requirement maps to a test. Successful output explicitly remains unauthenticated and lacks native or qualification fields. Existing offline contract tests run unchanged as compatibility coverage. Production authentication and runtime installation have no success claim in this phase; real proof stays open in the epic. Mandatory format/lint and CI contract tests remain enabled.

## Project References

RFC014, ADR0014 and approval issue3381 comment6280438100.

## Token Management Strategy

Medium: primary implementation with independent tests and review.

## Migration Notes

No existing caller or schema changes.

## Performance Considerations

Reject metadata before bounded archive hashing; constant memory; no member extraction.
