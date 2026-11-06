---
created_date: "2026-10-19"
document_status: final
closed_date: "2026-10-19"
---

# Research: 20261019211556-iso-media-provenance


## Alternatives considered and rejected
- Add fields to v1: bundle bytes and deployed Flatpak commit differ semantically. Browser and native v1 formats differ too (iso-builder:e2e/tests/builder.spec.js:595; pending tunaos:scripts/verify-experience-manifest.py:24).
- Import pending #3431 infrastructure: main e6f1a092 has no scripts/contracts or schemas; the pure contract needs no catalog, health or workflow changes.
- Self-hash media/archives: final hashes belong outside the bytes they identify, as the approved proposal requires.

## Chosen approach — evidence
Standalone offline v2 validation, typed roles, shared vectors and separate expected context preserve the approved boundary. Validation establishes consistency; authenticated collection remains separate.

## Files examined
- tunaos:RFC-PROCESS.md:37 — RFC, open issue, approach approval and ADR gates.
- tunaos:AGENTS.md:5 — spec/plan and bounded procedural self-approval.
- tunaos:tests/test_fork_config.py:15 — importlib pure Python tests and strict rejection.
- pending tunaos:scripts/verify-experience-manifest.py:122 — v1 lacks typed media identity.
- pending tunaos:scripts/contracts/targets.py:660 — independent expected context, no complete production caller.
- pending tunaos:scripts/contracts/evidence.py:24 — strict JSON and deterministic serialization.
- pending tunaos:.github/workflows/iso-e2e.yml:430 — bundle-only installer and ISO-as-overlay handoff.
- pending tunaos:live-iso/common/src/customize-live.sh:886 — frontend commit differs from bundle hash.
- iso-builder:.github/workflows/ci.yml:259 — WASM source, module and shim.
- iso-builder:e2e/tests/builder.spec.js:595 — browser evidence lacks final ISO hash.
- iso-builder:scripts/verify-catalog.py:71 and app/public/app.js:41 — metadata gates only.
- iso-builder:tests/test_qualification_admission.py:16 — repeated digest values need distinct role fixtures.
- iso-builder:native/catalog.go:108 — native admission remains a later adapter.

## External references
- https://github.com/tuna-os/iso-builder/issues/270#issuecomment-6277123450 — approved acyclic proposal.
- https://github.com/tuna-os/tunaOS/issues/3381#issuecomment-6277491364 — RFC014 reservation and approval.
- tunaOS#1187 — signing remains distinct from hashes.

## Prior plans / specs consulted
- single-fork-config-foundation/plan.md via CLI — main-based pure foundation precedent.
- Current ISO media spec via CLI. No registered design references returned; the public proposal defines the boundary.

## Open assumptions
- Initial implementation belongs only to registered tunaos. Registered docs needs no changes; iso-builder is a follow-on dependency.
- Future authenticated collection supplies reviewed context. Fixtures cannot prove honest collection.
- Resource observations need subject plus quantity, method and unit to avoid host/browser substitutions.

## Drafting assumptions
### Pure foundation (discovery)
- **Decision**: Isolated offline contract on main, no pending #3431 infrastructure imports.
- **Rationale**: Approved contract and tests first; production integration remains blocked.
- **Rejected**: Stack everything on #3431 or activate consumers without trusted evidence.
### Offline validator shape (architecture)
- **Decision**: Standard-library validator with schema and shared vectors.
- **Rationale**: Small pure API, no runtime dependency or integration side effects; schema tests offer an independent structural check.
- **Rejected**: Schema-only validation cannot express identity equality; importing #3431 tightly couples this stage to unmerged infrastructure.
### Applicable conventions (architecture)
- **Decision**: Apply main, evidence, behavior, test and prose conventions; omit generated-workflow and destructive-shell conventions from implementation.
- **Rationale**: This stage introduces no workflow generator or destructive operation.
- **Rejected**: Copy all conventions without relevance.

### Explicit schema oracle dependency (assemble)
- **Decision**: Add test-only jsonschema setup and a reviewed central pin.
- **Rationale**: Main does not install this package explicitly; tests cannot depend on accidental transitive availability.
- **Rejected**: Optional schema tests or a home-grown partial schema interpreter.

## Rehydration cues
Read the proposal, RFC policy, current spec through CLI and cited source lines. Check main and #3431 before adapter work. No large media builds for contract tests.

Within the approved shape, schema-only validation has low complexity but cannot enforce cross-document equality. A standard-library validator plus schema has medium complexity and covers those checks without a runtime dependency. Reusing pending #3431 has high integration cost and would import unrelated infrastructure. The middle option is selected.
