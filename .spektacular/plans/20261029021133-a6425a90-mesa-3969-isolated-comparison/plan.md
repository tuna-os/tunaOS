---
created_date: "2026-10-29"
document_status: final
closed_date: "2026-10-29"
---

# Plan: 20261029021133-a6425a90-mesa-3969-isolated-comparison

<!-- Created: 2026-10-29T04:51:13Z -->
<!-- Commit: 712ab320 -->
<!-- Branch: lab/mesa-3969-source-only-20261029 -->
<!-- Repository: https://github.com/tuna-os/tunaOS.git -->

## Overview

Prepare an explicitly activated Mesa comparison that distinguishes real software-rendered repair from hidden failure. Deliver the complete source path and safety proof now; builds, keys and guests require later exact-head approval.

## Conventions

- **Applied effect** — source checks never prove repaired rendering.
- **Evidence style** — exact identities and observed outcomes only.
- **Owned cleanup** — validate ownership; never prune globally.
- **Unchanged gates** — preserve tests, routing and deadlines.
- **Reviewed inputs** — fixed source/tool contracts, no production publisher.
- **Repository verification** — existing pytest, format/lint and prose contracts.
- **Current-main review** — inspect related work before publication.

## Architecture & Design Decisions

Use an isolated manual lab with one baseline and one dependency-complete immutable buildroot for complete original/patched Mesa sets. Prefer this to importing factory trust/publication policy or adding a mock snapshot subsystem. One temporary key serves both arms; exact source closure and immutable installed RPM headers reject mixing. See research.md#alternatives-considered-and-rejected.

Both arms receive identical lab instrumentation. A before-display unit runs the pinned C probe once per control, even when GDM cannot start. The unchanged helper owns visible login/lock/unlock and deletion; a bounded observer binds actual software renderer logs to live greeter/user identities. Preserve software/security policy and explicitly force the same GDM software condition. Missing devices are not EGL success; candidate crashes or incomplete evidence cannot become repair.

Official-repository, exact-head, first-attempt admission precedes effects. Authenticate bounded same-run transfer before extraction/load; scope all state and cleanup to owned resources. Default activation stays absent. Publish only source proof now; later builds, keys, guests and runtime acceptance need separate exact-head approval. These choices apply the effect, evidence, reviewed-input and unchanged-gate conventions.

## Component Breakdown

- **Safety core** — live admission, artifact authority, bounded consumption, sanitization and owned cleanup.
- **Package builder** — one frozen root/baseline, complete signed arms and exact measured identities; no publisher.
- **Guest collector/comparator** — pre-display pinned probe, unchanged real desktop gate and process-bound renderer proof.
- **Manual workflow** — fixed budgets, explicit activation, authenticated transfer and separate safe evidence.
- **Source verification** — behavioral safety coverage, real non-runtime smokes and precise operator limits.

## Data Structures & Interfaces

- **Admission** binds official repo, workflow, current run, first attempt and exact approved checkout head; live API, not a supplied receipt, establishes authority.
- **TransferManifest v1** binds fixed inputs, baseline/buildroot, signer, complete arms and file sizes/hashes to an immutable same-run artifact and upload digest.
- **PackageIdentity** includes exact SOURCERPM and immutable header SHA256, distinguishing same-NEVRA arms and unrelated drift.
- **Probe/Renderer/Arm/Comparison reports** retain actual statuses, live process/session identity, software policy and visible transitions; no inferred-success state.
- **OwnedRoot** binds run/head/role/UID to a safe marked directory; cleanup never targets unrelated state.

All records are bounded versioned JSON with strict keys/types/ranges. Interfaces establish admission, prepare a pair, verify transfer, run each arm and compare; any missing authority or required evidence refuses.

## Implementation Detail

Shell entry points own build and guest lifecycle; standard-library Python owns API/data validation and verdicts. Both privileged paths refuse before effects. Existing helpers remain unchanged; the lab adds only early probe collection and actual-renderer observation.

Seal inputs separately from sanitized evidence. Preserve real exit statuses and cleanup on failure/cancel. Source-only verification exercises safety without compiling packages, generating keys or booting guests; no production lane or implicit runtime fallback is introduced.

## Dependencies

- **Existing TunaOS build/tool contracts** — supported fixed-parent Albacore route, reused unchanged.
- **Fixed baseline/SRPM/full patch and helper commit** — owner-approved identities; helper merge not required.
- **Native container/RPM/compiler/GnuPG tools and Corral/KVM** — later owned execution only; no production credentials or publication.
- **GitHub read-only run/artifact APIs and standard-library Python** — explicit provenance and safety; no new Python library or settings.
- **Prior artifact-transport plan20261020002748-iso-artifact-transport-adapter** — identity reference, not a landing dependency; existing adapter unchanged.
- **Design documents this plan was built on: none.** Later exact-head runtime approval remains mandatory.

## Testing Approach

New pytest behavior tests target authority, artifact/path/size integrity, package/header drift, process-bound software evidence, truthful verdicts, secrets and owned cleanup. Preserve existing tests and gates. Real source-only CLI smokes run in hosted CI and observe refusals, integrity and filesystem effects without package builds, keys, guests or lab dispatch. Local builds and tests are forbidden by the owner.

- **Metric1: source safety** — affected suites, mandatory repository checks and real source-only smoke receipts.
- **Metric2: no automatic runtime** — actual changed-path admission and observed ordinary source CI at the published head, not a source-text wiring test.
- **Metric3: later attributable paired report** — **Manual — captured in the implementation test plan**.

Owner exact-head approval and review of real probe/software/UI evidence are **Manual — captured in the implementation test plan**. This host cannot establish signing/build compatibility, target logging or repaired desktop behavior; neither blocked campaign nor epic gains credit.

## Milestones & Tasks

### Milestone 1: Safe attributable inputs

**What changes**: Maintainers can review a complete original/patched package path that rejects unapproved or mixed inputs.

**Validation point**: Source safety and package-identity behavior passes; no build/key is executed.

#### - [ ] Task: Refuse unapproved runs and unsafe inputs
**Id:** 9a44b032-4109-4213-b652-cfa68254d1fa
**Repo:** tunaos
**Depends on:** none
**Execution:** agent

Reject unapproved work and unsafe inputs before cost. Keep cleanup limited to owned state.

*Technical detail:* [context.md#task-refuse-unapproved-runs-and-unsafe-inputs](./context.md#task-refuse-unapproved-runs-and-unsafe-inputs)

**Acceptance criteria**:
- [ ] Exact-head/manual/first-attempt authority fails closed.
- [ ] Substituted artifacts, unsafe paths and secret evidence refuse.

#### - [ ] Task: Prepare the coherent signed Mesa pair
**Id:** 38701040-c8b0-4779-b7d5-fd52065d11c8
**Repo:** tunaos
**Depends on:** none
**Execution:** agent

Prepare complete original/patched Mesa sets from one frozen root and baseline. Use isolated temporary signing, never production publication.

*Technical detail:* [context.md#task-prepare-the-coherent-signed-mesa-pair](./context.md#task-prepare-the-coherent-signed-mesa-pair)

**Acceptance criteria**:
- [ ] Fixed sources and complete coherent sets share the same root and baseline.
- [ ] Wrong-arm headers and unrelated package drift refuse; no build/key runs now.

### Milestone 2: Truthful repair evidence

**What changes**: The comparison distinguishes real software-rendered desktop success from crashes, stale logs or missing devices.

**Validation point**: Evidence/verdict boundaries pass; one-VM-per-arm helper lifecycle is preserved, not exercised now.

#### - [ ] Task: Compare real software-rendered desktop behavior
**Id:** 2e43e5d7-60cf-4bf3-bf0d-e5d81044e63a
**Repo:** tunaos
**Depends on:** none
**Execution:** agent

Preserve all four probe outcomes even when GDM crashes. Require actual software-rendered login, lock and unlock.

*Technical detail:* [context.md#task-compare-real-software-rendered-desktop-behavior](./context.md#task-compare-real-software-rendered-desktop-behavior)

**Acceptance criteria**:
- [ ] One bounded VM per arm preserves pinned helpers and deadlines.
- [ ] Crashes, stale evidence and missing transitions cannot become repair.

### Milestone 3: Review without automatic cost

**What changes**: One source candidate offers a bounded manual experiment while runtime stays held.

**Validation point**: Source smokes/checks and ordinary hosted CI pass; no automatic image/guest job is admitted.

#### - [ ] Task: Offer one bounded manual workflow
**Id:** c7735ebf-0881-4c23-a6d2-c15bfa1b0760
**Repo:** tunaos
**Depends on:** none
**Execution:** agent

Offer one manual experiment without automatic cost. Require exact-head activation and bounded authenticated transfer.

*Technical detail:* [context.md#task-offer-one-bounded-manual-workflow](./context.md#task-offer-one-bounded-manual-workflow)

**Acceptance criteria**:
- [ ] Missing approval fails visibly; no settings or production changes.
- [ ] Read-only permissions, fixed caps and exact same-run inputs are enforced.

#### - [ ] Task: Verify and publish the source-only candidate
**Id:** 7e193f50-79f9-4f1a-8e43-f26994c7b189
**Repo:** tunaos
**Depends on:**
- 9a44b032-4109-4213-b652-cfa68254d1fa — Refuse unapproved runs and unsafe inputs
- 38701040-c8b0-4779-b7d5-fd52065d11c8 — Prepare the coherent signed Mesa pair
- 2e43e5d7-60cf-4bf3-bf0d-e5d81044e63a — Compare real software-rendered desktop behavior
- c7735ebf-0881-4c23-a6d2-c15bfa1b0760 — Offer one bounded manual workflow
**Execution:** agent

Exercise safety without running the experiment. Publish exact hosted-CI source proof and the remaining runtime hold.

*Technical detail:* [context.md#task-verify-and-publish-the-source-only-candidate](./context.md#task-verify-and-publish-the-source-only-candidate)

**Acceptance criteria**:
- [ ] Source smokes/checks pass with zero builds, keys, guests or dispatch.
- [ ] Published source CI admits no automatic runtime and docs preserve epic holds.

## Open Questions

No unresolved source implementation questions. Runtime sizes, duration, binary logging and repair remain held manual observations, never assumptions of success.

## Out of Scope

- No current builds, key generation, guests, activation, dispatch or merge; #3969 runtime needs later exact-head approval.
- No encrypted-unlock diagnosis or ISO-install qualification; #4038 and #3380 remain separate.
- No TOML completion or blocked eight-image campaign; #3668/#4029 retain acceptance obligations.
- No R2/download/production publishing or trust change.
- No helper/gate/test weakening, retry or cleanup suppression; #4052 fixtures remain separate.
- No browser deployment or engine pin update; PR307/423 have separate authority.
- No external runner-capacity fix or automatic epic closure.

These exclusions do not remove the broader ISO/configuration objective.

