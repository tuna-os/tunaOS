---
created_date: "2026-09-27"
document_status: draft
---

# Plan: Privacy-respecting TunaOS countme

Status: Local implementation and verification complete within the limits below; collector and dashboard production deployment is complete; image rollout and pilot validation remain pending.

<!-- Created: 2026-09-27 -->
<!-- Commit: 7c9efe4f10c6ba053373adebe2495e5ade67daf8 -->
<!-- Branch: main -->
<!-- Repository: tuna-os/tunaos -->

## Overview

TunaOS gains adoption estimates across official installed images while preserving user control. Maintainers and the public see the same weekly reporting trends without individual tracking.

## Conventions

- **Assert applied state** — verify effective units, masks and metadata after all desktop/overlay copies in built images.
- **Derive data** — generate collector categories and image coverage from build configuration.
- **Declared gates run** — register any new green gate in green-criteria with workflow evidence.
- **Evidence style** — cite pinned upstream source and include measured image outcomes.
- **Main and rebase** — verify open PRs and rebase before implementation publication.
- **Bats/pytest/just** — follow existing shell and Python tests; wire Worker runtime tests into the normal PR gate.
- **Pinned tools** — source external test/build tool pins from image-versions; use native lockfiles for package dependencies.
- **STE budget** — do not raise the prose budget for this change.
- **Troubleshooting** — document identity, timer and privacy failures with measured cause and fix.

## Architecture & Design Decisions

Use a package-manager-independent reporter with local persistent state, a Cloudflare Worker request boundary and D1 atomic aggregate counters. The collector stores a total and independent variant, flavor, architecture and age margins, with no device or event records. The public reader publishes frozen closed-week values with rounding and whole-dimension suppression when any category is small.

Privacy takes priority over exact uniqueness: the client records a weekly attempt before POST and never retries an ambiguous response. Under-counting is explicit. There is no server device hash, shared image secret or individual retention; Cloudflare transport processing is disclosed separately. Account logging and database-history reconstruction review are required before rollout. Aggregate counters alone do not remove the possibility of inferring category tuples from database history.

Image metadata preserves original canonical variant and requested flavor. The built-image convention requires verifying effective service state after upstream copies, including overlays. A persistent opt-out, explicit live/CI exclusions and a no-network build path protect user choice and the denominator. Alternatives and evidence are in [research.md](./research.md#alternatives-considered-and-rejected).

The implementation spans tunaos and the sibling tuna-os/docs repository. On 2026-09-27 the user requested full implementation and tests, selected default participation with persistent opt-out, and identified the tunaos.org domain owner. Cloudflare authentication is absent; production provisioning remains pending. Procedural steps can be self-approved under AGENTS.md; this does not approve an RFC or claim a deployed service.

## Component Breakdown

- **Image metadata producer** preserves the canonical original matrix category for the reporter and refreshes overlay output.
- **Reporter and timer** validate eligibility, honour user controls, manage local age/week state and attempt a bounded anonymous POST.
- **Collector** validates a bounded categorical payload and commits aggregate increments without observing identity headers.
- **Publisher** freezes privacy-safe closed-week counters and availability metadata for all public output formats.
- **Dashboard** renders the published weekly trend and separate margins with explicit missing/suppressed labels.
- **Coverage contract** derives official cells and verifies installed metadata, controls and effective service state.

## Data Structures & Interfaces

ReportV1 = {schema: 1, variant: OfficialVariant, flavor: OfficialFlavor, arch: OfficialArchitecture, age_bucket: 1|2|3|4}.

LocalState = {first_observed_epoch, last_attempted_utc_week}; it never enters image layers or requests.

AggregateKey = {utc_week, dimension: total|variant|flavor|arch|age_bucket, category}; AggregateValue = integer count. Store each margin independently, never combined tuples.

PublicWeek = {week_start, week_end, methodology_version, generated_at, health, total, margins}. Counts are rounded integers or null with an explicit collecting/suppressed/unavailable/degraded status. Exports and dashboard consume the same frozen values.

POST /v1/report returns 204 only after a durable atomic batch, fixed 4xx for validation and fixed 5xx for operational failure. Public GET endpoints expose closed-week snapshots only. The proposed hostname is unprovisioned.

## Implementation Detail

Follow existing shell orchestration and image-copy conventions for the reporter. Keep identity separate from stage names, compare and flush all attempt-state writes durably under a lock, reject corrupt/future state and never enable telemetry through a silent default for unknown images. Persist opt-out in administrator state across upgrades and switches.

Use a small Worker module with strict categorical validation and prepared aggregate SQL statements; no request-data logs or raw queues. Enforce body limits while reading the stream, not just from a supplied content length. Use a server-assigned UTC week and commit counters atomically; publish from a consistent snapshot after closure. Keep collector tests in the Cloudflare local runtime so concurrency and batch rollback assertions exercise the actual storage API.

Exclude live and CI guests through runtime markers, preserving normal reporting for installed VMs. Disable inherited reporters after copies and verify final effective state. Dashboard assets use no external trackers. Draft decisions follow the [RFC](../../../docs/rfc/rfc012-private-adoption-metrics.md).

## Dependencies

- Design documents this plan was built on: none. Spec design-reference lookup returned zero refs and zero unresolved. The sibling RFC is a draft proposal, not an approved binding design.
- TunaOS build configuration and flavor resolver provide identity and coverage; their data flow needs an original-flavor parameter.
- systemd and Python 3 (standard library with flock) must be available on every image family; no dnf-only runtime dependency.
- Cloudflare Workers and D1 provide the proposed collector/storage; account, hostname and logging review precede production enablement.
- Cloudflare local runtime and pinned Wrangler tooling provide Worker verification; integrate their checks into existing PR testing.
- RFC-PROCESS.md requires a tracking issue/number and maintainer sign-off before architectural rollout; no issue is published by this draft.

## Testing Approach

Use bats with mocked clock/network and temporary state to verify weekly attempts, exclusions, schema, locking, state corruption and opt-out. Use Python contracts for configuration-derived image coverage and final artifacts. Worker runtime tests verify concurrent UPSERT batches, rollback, bounded body reads, aggregate-only storage, pruning and suppression across every export.

Built-image and installed-guest tests verify true identity and unit behaviour for each package-manager family, a desktop/base and an overlay. Live and CI boot tests target a synthetic collector and prove zero requests. Never infer effective reporting from a COPY or service invocation alone.

Success metric: publication within 24 hours of UTC week closure — behavioural test with fake server time and publisher scheduling; production delivery latency is Manual — captured in the implementation test plan. Freshness and health labels — behavioural snapshot/API tests. Public comparison value — Manual — captured in the implementation test plan, using maintainer/contributor review of the same published data. Account logging/provider retention — Manual — captured in the implementation test plan before enablement.

## Milestones & Phases

### Milestone 1: Inspect anonymous reporting safely

**What changes:** A disabled client and synthetic collector make privacy behaviour reviewable before any rollout.

#### - [x] Phase 1.1: Anonymous installed reporter

**Repo:** tunaos

Users gain a small reporting client with persistent opt-out controls. The client defaults on as the user requested; the collector stays disabled until production setup.

*Technical detail:* [context.md](./context.md#phase-11-anonymous-installed-reporter)

**Acceptance criteria**:

- [x] Reports contain only approved categories and broad age.
- [x] Disabling persists across upgrade and image switch.
- [x] Offline, clock and acknowledgement failures follow the documented weekly attempt policy.

#### - [x] Phase 1.2: Private collector and public views

**Repo:** tunaos

Contributors can inspect a synthetic weekly dashboard. The collector and outputs store and expose only the planned aggregate data.

*Technical detail:* [context.md](./context.md#phase-12-private-collector-and-public-views)

**Acceptance criteria**:

- [x] Concurrent requests cannot lose increments or partially commit.
- [x] Small groups cannot be recovered by subtraction across exports.
- [x] No raw events or client identifiers enter application storage.

### Milestone 2: Cover every installed image

**What changes:** Every official image preserves its identity and user control; excluded boot modes make no reports.

#### - [ ] Phase 2.1: Every image has the correct category

**Repo:** tunaos

Base, desktop and overlay images receive the same client and user controls. Their reports identify the original image category rather than a build-stage default.

*Technical detail:* [context.md](./context.md#phase-21-every-image-has-the-correct-category)

**Acceptance criteria**:

- [ ] All official cells have correct canonical metadata and effective unit state.
- [ ] Inherited Bluefin reporters cannot run on TunaOS.

#### - [ ] Phase 2.2: Live media and CI stay outside counts

**Repo:** tunaos

Users running installed VMs can participate. Live installers, build containers and automated boot guests contribute no adoption reports.

*Technical detail:* [context.md](./context.md#phase-22-live-media-and-ci-stay-outside-counts)

**Acceptance criteria**:

- [ ] Live and CI boot scenarios produce zero requests.
- [ ] Installed guests send the correct category once per week.
- [ ] A failing collector leaves normal system operation intact.

### Milestone 3: Publish adoption estimates

#### - [x] Phase 3.0: Public metrics site

**Repo:** docs

Publish /metrics with weekly trends and separate category charts, a same-origin API proxy, public JSON and CSV, accessibility tests, strict feed validation and explicit missing/suppressed states. A matrix-derived category file rejects unknown labels.

**Acceptance criteria:** Site unit checks, production build, browser smoke and accessibility checks pass without trackers or invented adoption data.


**What changes:** After maintainer decisions and a volunteer pilot, public weekly trends explain participation and gaps.

#### - [ ] Phase 3.1: Reviewed rollout and public adoption history

**Repo:** tunaos

A reviewed privacy notice and participation choice precede reporting by users. A volunteer pilot validates the production path before all official images are enabled.

*Technical detail:* [context.md](./context.md#phase-31-reviewed-rollout-and-public-adoption-history)

**Acceptance criteria**:

- [ ] Maintainer approves collection, participation default and publication policy.
- [ ] Account logging, DNS/TLS, retention and budget are verified before real-client collection.
- [ ] Public output explains coverage gaps, age semantics and estimated installations.

## Open Questions

Whether all supported systemd versions allow the proposed sandbox and state access must be verified in real installed guests during implementation. If a family fails, stop before enabling that family and revise the sandbox with measured evidence.

No product decision is treated as an implementation-time unknown: participation default, public suppression policy, account ownership and budget are explicit pre-rollout decisions in the draft RFC and Phase 3.1.

## Out of Scope

- Exact unique users, daily/monthly unique counts or per-device retention.
- Location, application usage, sessions or richer version/channel metadata.
- Registry downloads as installation metrics.
- Production cloud deployment or timer enablement by this planning change.
- A claim of verified authenticity for an unauthenticated anonymous report.



## Local verification evidence (2026-09-27)

- Client/image pytest: 200 passed across client, image and CI checks, including all declared variant/flavor installer outputs and generated category equality.
- Collector: 10 real Miniflare/D1 tests passed; Worker build and deployment dry-run passed with Wrangler 4.141.0. Full npm audit reports zero vulnerabilities after patching development dependencies.
- Cross-repository integration: 23 synthetic D1 reports produce a frozen rounded count of 20, consumed by the docs Worker proxy with visitor headers and query discarded.
- Built artifact: localhost/tunaos-countme-proof:20260927 layered onto cached yellowfin RPM image; correct original flavor, generated allowlist, default timer, six inherited masks and no container request/state.
- Site: preflight, production build, browser smoke checks including native API navigation, and accessibility checks passed (zero axe violations). Wrangler deployment dry-run passed.
- Repository formatting and checks passed. The full test run found two failures: a host-dependent absent-qemu-img fixture and the new countme check using a relative path from an imported Just module. Both were fixed; their 33-case bats file and 11-case pytest module reruns passed. The full pytest run otherwise reported 1999 passed, 16 skipped and 70 subtests. The original full command exited nonzero; a second complete suite was not run. Corral exclusion tests passed all 8 cases and CI contract plus new boot gate tests passed all 41 cases.

Image integration and exclusions are implemented. Phases2.1 and2.2 remain unchecked against their stronger full-boot acceptance criteria: representative installed guests for every family and ARM were not booted locally. Phase3.1 remains pilot validation and image rollout work. Wrangler device OAuth succeeded and the collector is deployed with its production D1 binding. RFC sign-off, account-wide logging access and account budget controls are not claimed.

## Production deployment evidence (2026-09-27)

- Domain ownership verified through the Cloudflare zones API. Dedicated D1 database created and migration applied remotely. Collector deployed as `tunaos-countme`, version `dc9ad8fa-fe9d-49e5-9d50-f84f9bba9dd3`.
- `https://countme.tunaos.org/health` returned HTTP 200 with collection enabled. Invalid `{}` report returned HTTP 400; no synthetic valid reports were sent to production. JSON endpoint returned an empty closed-week list.
- Effective Worker settings show Logpush false and no Tail consumers; workers.dev and preview subdomain settings are false. Account-wide Logpush inspection returned HTTP 403 with this OAuth token; account-level retention and spend controls are not claimed. Public notice discloses automatic D1 recovery history for up to 30 days.
- Collector tests reran with 10 passing cases. Site preflight and new-document Markdown lint passed after the retention notice update. Site deployed as `tunaos-org`, version `e9798ba3-71d0-4168-bc67-a03986d06ec9`. Live `/metrics` returned HTTP 200, hydrated without page errors, and had zero axe violations. `/api/adoption` GET/HEAD returned HTTP 200; JSON passed the shared validator. Native workerd service-binding integration passed after correcting the unsupported `redirect: "error"` option to `"manual"` with redirect rejection. Temporary diagnostic headers were removed. Repository `just fix` and `just check` passed. No synthetic valid reports were sent to production.
