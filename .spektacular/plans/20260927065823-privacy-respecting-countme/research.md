---
created_date: "2026-09-27"
document_status: draft
---

# Research: Privacy-respecting TunaOS countme

## Alternatives considered and rejected

- Upstream dnf countme: cannot describe non-RPM TunaOS installations; Bluefin LTS source uses dnf makecache, while TunaOS supports apt/pacman/zypper/emerge.
- GHCR pulls: includes CI, mirrors and repeated updates, not a reporting-installation denominator.
- Device hashes/UUIDs: creates weekly or persistent linkage; old Dakota PR 807 closed unmerged.
- KV counters: eventually consistent read-modify-write risks losing increments; D1 atomic batches fit the independent-margin schema.
- Durable Objects: viable if serialization logic grows; unnecessary for the proposed atomic database operations.

## Chosen approach — evidence

Dakota shared countme keeps local epoch/lastrun and sends categories without a device identifier. D1 batch API documents rollback of the full batch on error. Workers logging defaults must be explicitly disabled. See source permalinks and Cloudflare documentation in docs/rfc/rfc012-private-adoption-metrics.md.

## Files examined

- tunaos:build_scripts/40-services.sh:150,651,661 — package-manager early exits and RPM-only countme enablement.
- tunaos:build_scripts/90-image-info.sh:35-55 — flavor from stage and constant latest tag; canonical original variant available separately.
- tunaos:scripts/resolve-flavor.sh:86 — overlay DESKTOP_FLAVOR becomes desktop.
- tunaos:scripts/build-image-inner.sh:73-86 — original variant passed separately from publish name; full flavor argument required.
- tunaos:Containerfile.overlay:141-148 — re-copy assets and re-run image info; final effect must survive copies.
- tunaos:Containerfile.arch:284, Containerfile.debian:280, Containerfile.gentoo:600, Containerfile.opensuse:287 — upstream shared payload copied after own system files.
- tunaos:live-iso/common/src/customize-live.sh:961 — live customization, separate from installed payload.
- tunaos:tests/bats/test_resolve_flavor.bats:1 — shell test conventions for stage/flavor resolution.
- tunaos:tests/test_ci_contract.py:1 — declared green gate verification.
- tunaos:just/utilities.just:1 — checks, test runners and prose budget.

## External references

- projectbluefin/common a9ec4541efa8919581d13f50e800675c5f245a46 — Dakota reporter, daily timer, sandbox, opt-out and bootc identity behavior.
- projectbluefin/bluefin-lts 2170146f03de894f13af8d8fd80020ec386e8b01 — dnf makecache workaround and countme cookie semantics.
- https://github.com/projectbluefin/common/pull/807 — historical hash proposal; measured closed and unmerged.
- https://developers.cloudflare.com/d1/worker-api/d1-database/ — transaction/batch guarantee.
- https://developers.cloudflare.com/workers/observability/logs/workers-logs/ — new Workers logging default.
- https://developers.cloudflare.com/d1/reference/time-travel/ — backup history makes aggregate-only writes useful.
- https://developers.cloudflare.com/kv/concepts/how-kv-works/ — eventually consistent counter risk.

## Prior plans / specs consulted

Current countme spec via spektacular spec file read; scope and success metrics carried into this plan. No previous countme plan was found; knowledge search countme returned no hits. RFC 011 and ADR 0010 describe the repository workflow; they do not approve a telemetry architecture.

## Open assumptions

Cloudflare account logging/retention can meet the notice; confirm before production. Systemd sandbox/state access works across image families; prove in guests. Opt-out survives switch and installer choice can be written before first eligible timer; prove with installation tests. Default-on, suppression at 10 and 104-week aggregate retention are proposals pending maintainer decision, not settled requirements for rollout.

## Rehydration cues

Read the spec and this plan through Spektacular, then docs/rfc/rfc012-private-adoption-metrics.md and AGENTS.md. Refresh main and open PRs. Fetch pinned upstream sources again before implementation; review actual identity flow and later COPY stages. Run just fix/check/test and verify built outputs. Never treat agent workflow completion as RFC sign-off.

## Drafting assumptions

### Identifier-free counting (architecture)
- Decision: choose approximate weekly reports over per-device hashing.
- Rationale: meets adoption trends with less stored linkage.
- Rejected: rotating machine-id hashes and persistent UUIDs create identity/retention concerns.

### Cloudflare and D1 (architecture)
- Decision: propose Workers plus aggregate-only D1.
- Rationale: atomic batch counters and simple public exports without maintaining a server.
- Rejected: KV increments are eventually consistent; Durable Objects add lifecycle work unnecessary for this schema.

### Publication limits (data structures)
- Decision: propose closed weeks, rounding to 10, whole-margin suppression for any category 1–9 and 104-week retention.
- Rationale: bound fine-grained disclosure and simplify storage.
- Rejected: public live counts, exact sparse tables and combined filters invite inference.

### Workflow review (walkthrough)
- Decision: agent procedural review under user AGENTS.md unattended-step rule.
- Rationale: complete reviewable planning without repeated confirmation stops.
- Rejected: treating procedural review as production or maintainer approval. Participation default remains unresolved.

## Independent design review

Review found distributed-week skew, attempt-marker crash durability, D1 history reconstruction, first-report choice timing, and rejected-traffic cost risks. The RFC now explicitly qualifies server-week uniqueness, requires durable local flush under lock, blocks enablement pending history/privacy review, requires installer/first-boot handoff, and separates ingestion caps from infrastructure limits. Representative boots supplement generated all-cell artifact checks and real upgrade/switch tests.
