---
created_date: "2026-10-19"
document_status: final
closed_date: "2026-10-19"
---

# Context: 20261019211556-iso-media-provenance


## Current State Analysis

The initial main baseline had a two-line shfmt failure. Separate PR #3483 fixes only those tabs. This branch temporarily uses its exact commit 4c51113bd38c52095d42eb08b881e4cdfebd8ab9 as an explicit dependency; retarget and recheck after it lands.
Main e6f1a092 lacks the pending #3431 qualification infrastructure. Browser v1 and native v1 differ and do not bind final media. See research.md for exact source references.

## Per-Phase Technical Notes
### Phase 1.1: Define the typed media contract

File changes: new docs/rfc/rfc014-iso-media-provenance.md; new docs/adr/0014-iso-media-provenance-contract.md; append RFC014 to docs/rfc/README.md and ADR0014 to docs/adr/README.md; new schemas/iso-media-provenance-v2.schema.json. Recheck ADR numbering before publication. Requirement mapping: exact-media and typed-input behavior live in the schema; independent trust, version migration and safe rollout also live in RFC/ADR. Do not import pending #3431 schemas.

Closed browser shape: schemaVersion=2, kind=qualification-evidence, half=browser; media {sha256,sizeBytes}; typed input_descriptors source/overlay/installer/engine; build_request_sha256, recipe_sha256, config_sha256; browser {product,version}; resources with subject, quantity, unit, source, method, value; declared run coordinates. Source is a digest-pinned OCI platform manifest with platform and CPU baseline. Overlay is an OCI manifest with source baseDigest. Frontend uses Flatpak app/ref/arch/deployedCommit, optional bundleSha256. Engine uses WASM module hash and source revision; runtime shim hash is separate.

Native shape: schema=QualificationEvidence/v2; final media identity; browser receipt hash; separate harness revision and QEMU digest; exact source/booted digest, offline network state, GUI completion and target-only reboot observations for plain and encrypted modes. Expected context is not embedded: repository, reviewed workflow definition revision/path, source/harness revisions, run ID/attempt, selected artifact ID/archive hash, receipt and media identities, expected descriptors. Unknown/missing versions fail v2 dispatch; recognized v1 formats are diagnostic-only. Context comparison does not authenticate API responses.

Complexity: Medium. Token estimate: ~8k. Agent strategy: schema and docs may be drafted independently, with one integration owner.

### Phase 2.1: Validate evidence without production activation

File changes: new scripts/iso_media_provenance.py; new tests/test_iso_media_provenance.py; new tests/fixtures/iso-media-provenance-v2/cases.json and tiny deterministic media fixture; test-only dependency setup in .github/workflows/test.yml:109 and just/utilities.just:107, with its reviewed pin in image-versions.yaml. Use tests/test_fork_config.py:15 importlib convention. Reuse ideas from pending scripts/contracts/evidence.py:24 for strict JSON, without importing its package.

The API parses strict JSON, validates one role, and compares browser/native receipt bytes and media bytes against a separate expected-context object. Required observed transport metadata supplies run/artifact coordinates for comparison; no receipt-derived fallback is permitted. Both context inputs are caller-supplied at this pure boundary. Return consistency_valid with authentication=not_authenticated, never a qualified flag. The later collector must obtain trusted observations independently. Hash the exact supplied bytes, not a reserialized claim. Reject duplicate keys, non-finite values, bool-as-int, invalid versions, unknown fields, wrong kinds, placeholder browser names/version, role swaps, mismatched source/base/platform, mismatched media size/digest, wrong native browser receipt reference, wrong workflow/source/run/attempt/artifact and missing required native observations. Keep distinct role digest values in fixtures. Valid remote-installed frontend has deployedCommit without bundleSha256. Resources use explicit subjects, sources and source/method pairings; browser-reported memory is not measured host memory. Test quantity-specific units and strict positive finite prerequisites.

Run schema validation and pure API tests on shared vectors. Runtime remains standard library. Current test setup lacks explicit jsonschema: add a reviewed development pin and install it in local/CI test setup. Run just fix, just check and focused pytest; full CI remains required. Review the diff for zero production workflow/catalog changes; only test-dependency setup may change. Later consumers, authenticated collector and real installation proof remain open on #270/#3470/#3381.

Complexity: Medium. Token estimate: ~12k. Agent strategy: parallel negative-case review with sequential module integration.

## Testing Strategy
Phase 1 validates schema structure and governance consistency. Phase 2 executes shared positive and adversarial vectors through the schema oracle and pure checker, then local format/lint and full CI. Real browser/native execution remains a later integration gate.

## Project References
RFC-PROCESS.md, approved iso-builder#270 proposal, tunaOS#3381 approval, and pending #3431 are the relevant boundaries. Only registered tunaos changes in this stage.

## Token Management Strategy
Both phases are medium complexity, roughly 8k and 12k tokens. Draft independent artifacts in parallel where available; integrate sequentially.

## Migration Notes
No existing receipts are rewritten. Recognized v1 input stays diagnostic-only; no production consumer is switched.

## Performance Considerations
Tests use tiny media bytes. Production integration should stream hashes over large media instead of loading archives into memory; the pure checker bounds stream reads by the independently expected size and requires a zero starting position for seekable streams. This stage makes no performance qualification claim.

## Procedural review

The plan walkthrough was self-approved under AGENTS.md's no-person-present rule.
The review retained the main-based pure stage, separate expected context, explicit
test dependency and unchanged production policy. This procedural approval does
not substitute for the maintainer approach approval or later runtime proof.
