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

#### - [x] Task: Refuse unapproved runs and unsafe inputs
**Id:** 9a44b032-4109-4213-b652-cfa68254d1fa
**Repo:** tunaos
**Depends on:** none
**Execution:** agent

Reject unapproved work and unsafe inputs before cost. Keep cleanup limited to owned state.

*Technical detail:* [context.md#task-refuse-unapproved-runs-and-unsafe-inputs](./context.md#task-refuse-unapproved-runs-and-unsafe-inputs)

**Acceptance criteria**:
- [x] Exact-head/manual/first-attempt authority fails closed.
- [x] Substituted artifacts, unsafe paths and secret evidence refuse.

#### - [x] Task: Prepare the coherent signed Mesa pair
**Id:** 38701040-c8b0-4779-b7d5-fd52065d11c8
**Repo:** tunaos
**Depends on:** none
**Execution:** agent

Prepare complete original/patched Mesa sets from one frozen root and baseline. Use isolated temporary signing, never production publication.

*Technical detail:* [context.md#task-prepare-the-coherent-signed-mesa-pair](./context.md#task-prepare-the-coherent-signed-mesa-pair)

**Acceptance criteria**:
- [x] Fixed sources and complete coherent sets share the same root and baseline.
- [x] Wrong-arm headers and unrelated package drift refuse; no build/key runs now.

### Milestone 2: Truthful repair evidence

**What changes**: The comparison distinguishes real software-rendered desktop success from crashes, stale logs or missing devices.

**Validation point**: Evidence/verdict boundaries pass; one-VM-per-arm helper lifecycle is preserved, not exercised now.

#### - [x] Task: Compare real software-rendered desktop behavior
**Id:** 2e43e5d7-60cf-4bf3-bf0d-e5d81044e63a
**Repo:** tunaos
**Depends on:** none
**Execution:** agent

Preserve all four probe outcomes even when GDM crashes. Require actual software-rendered login, lock and unlock.

*Technical detail:* [context.md#task-compare-real-software-rendered-desktop-behavior](./context.md#task-compare-real-software-rendered-desktop-behavior)

**Acceptance criteria**:
- [x] One bounded VM per arm preserves pinned helpers and deadlines.
- [x] Crashes, stale evidence and missing transitions cannot become repair.

### Milestone 3: Review without automatic cost

**What changes**: One source candidate offers a bounded manual experiment while runtime stays held.

**Validation point**: Source smokes/checks and ordinary hosted CI pass; no automatic image/guest job is admitted.

#### - [x] Task: Offer one bounded manual workflow
**Id:** c7735ebf-0881-4c23-a6d2-c15bfa1b0760
**Repo:** tunaos
**Depends on:** none
**Execution:** agent

Offer one manual experiment without automatic cost. Require exact-head activation and bounded authenticated transfer.

*Technical detail:* [context.md#task-offer-one-bounded-manual-workflow](./context.md#task-offer-one-bounded-manual-workflow)

**Acceptance criteria**:
- [x] Missing approval fails visibly; no settings or production changes.
- [x] Read-only permissions, fixed caps and exact same-run inputs are enforced.

#### - [x] Task: Verify and publish the source-only candidate
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
- [x] Source smokes/checks pass with zero builds, keys, guests or dispatch.
- [x] Published source CI admits no automatic runtime and docs preserve epic holds.

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


## Source verification record

These task checkboxes attest the implemented source contracts, behavioral safety and reviewed structure, not an executed native experiment. Hosted Test40845773673 tested source3c610a7aa01ccedb3d560dd3281de1074a0ba98f as merge316b0f15cd30489e9787afe5873eed58b12a9114 against94bd7d4ee6ec3753ff6717ffb98163c1760b33ea:6831passed,16skipped,129passing subtests, including364 new Mesa cases and the real CLI smoke. Primary Python3.10/3.15, lint, Just Fix and prose passed; image/bootc jobs were skipped. Upstream #4067 supplied the old fixture repair; no frozen test or gate was edited in this candidate. Metric3 and owner exact-head approval remain unexecuted manual obligations. No lab keys, native builds, guests, activation, dispatch, merge, production publication or R2 mutation.

## Changelog

### 2026-10-29 — Task: Refuse unapproved runs and unsafe inputs

**What was done**: Implement exact-head/manual/first-attempt admission, producer/artifact authority, bounded integrity validation, semantic redaction and marker-bound cleanup. Hosted behavior checks and the real CLI smoke passed without a lab runtime.

**Deviations**: None against the final source plan.

**Files changed**:
- `tunaos: tests/manual/mesa_3969.py`
- `tunaos: tests/test_mesa_3969_safety.py`
- `tunaos: tests/manual/test_mesa_3969_source_smoke.py`

**Discoveries**: Archive integrity is not authority; authenticate the independent server digest and exact successful producer before consumption. Preserve the original runner UID through sudo and decode JSON strings before filtering secrets.

### 2026-10-29 — Task: Prepare the coherent signed Mesa pair

**What was done**: Implement the complete fixed-input original/patched SRPM path, one frozen dependency root/baseline, complete signed package sets and immutable RPM-header arm checks. Package behavior cases passed; native builds, signing and RPM/GPG compatibility remain unexercised.

**Deviations**: None against the final source plan.

**Files changed**:
- `tunaos: tests/manual/mesa-3969-build.sh`
- `tunaos: tests/manual/mesa_3969_packages.py`
- `tunaos: tests/test_mesa_3969_packages.py`

**Discoveries**: The normal native wrapper retries and can globally prune Buildah; the lab instead uses one unchanged Containerfile build with canonical generated context and reviewed arguments. Same NEVRA/shared signer does not establish selected-arm identity.

### 2026-10-29 — Task: Compare real software-rendered desktop behavior

**What was done**: Implement the before-display pinned probe, sequential one-VM-per-arm unchanged helper lifecycle, process-bound Cogl renderer observation and fail-closed comparison. Guest evidence/verdict cases passed; no VM, compositor or repair was exercised.

**Deviations**: None against the final source plan.

**Files changed**:
- `tunaos: tests/manual/mesa-3969-guest.sh`
- `tunaos: tests/manual/mesa_3969_guest.py`
- `tunaos: tests/manual/mesa-3969-probe.service`
- `tunaos: tests/test_mesa_3969_guest.py`

**Discoveries**: A control can fail before login; early probe collection must preserve those failures without a second probe VM. Probe exits3/4 denote an unexercised device path, never successful EGL initialization; binary Cogl formatting still needs real observation.

### 2026-10-29 — Task: Offer one bounded manual workflow

**What was done**: Offer a dispatch-only, default-refusing workflow with fixed resource caps, same-run authenticated transfer and separate sanitized evidence. Observed PR CI skipped image and bootc compilation jobs.

**Deviations**: The new real CLI smoke is discovered by existing pytest instead of a separate PR workflow. Existing Test/lint workflows, fork classifier, assertions and image filters remain unchanged.

**Files changed**:
- `tunaos: .github/workflows/mesa-3969-compare.yml`
- `tunaos: docs/CI_SPEC.md`

**Discoveries**: Editing a registry script under scripts/ admits the image matrix through the unchanged path filter; direct new pytest discovery avoids that coupling without weakening a gate.

### 2026-10-29 — Task: Verify and publish the source-only candidate

**What was done**: Publish draft PR4058 and hosted exact-head proof: source3c610a7a / merge316b0f15,6831passes,16skips,129passing subtests, including364 new Mesa cases and a real CLI smoke. Primary Python3.10/3.15, lint, Just Fix and prose passed; no automatic image jobs or lab runtime.

**Deviations**: All verification runs in CI per the owner. Incorporated main's already merged #4067 fixture repair by rebase instead of modifying frozen assets. Corrected only new prose without a budget change or opt-out.

**Files changed**:
- `tunaos: docs/TESTING.md`
- `tunaos: docs/ci-troubleshooting.md`
- `tunaos: .spektacular/plans/20261029021133-a6425a90-mesa-3969-isolated-comparison/test-plan.md`
- `tunaos: .spektacular/specs/20261029021133-a6425a90-mesa-3969-isolated-comparison.md`
- `tunaos: .spektacular/plans/20261029021133-a6425a90-mesa-3969-isolated-comparison/context.md`
- `tunaos: .spektacular/changelog/20261029021133-a6425a90-mesa-3969-isolated-comparison.md`
- `tunaos: .spektacular/changelog/tunaos/20261029021133-a6425a90-mesa-3969-isolated-comparison.md`

**Discoveries**: PR CI tests a merge, not necessarily the raw branch head; retain both and the tested base. Source readiness cannot close the Mesa, ISO, encrypted-install or TOML acceptance holds.
