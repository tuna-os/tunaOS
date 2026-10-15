---
created_date: "2026-09-27"
document_status: draft
---

# Context: Privacy-respecting TunaOS countme

## Current State Analysis

Main 7c9efe4f matched origin/main during discovery. RPM-only countme calls exist; no all-family TunaOS collector exists. Stage metadata is not original flavor identity. Upstream reporters are copied through shared assets and need effective-state verification.

## Per-Phase Technical Notes

### Phase 1.1: Anonymous installed reporter

New system_files/usr/libexec/tunaos-countme, system_files/usr/lib/systemd/system/tunaos-countme.service and timer; tests/bats/test_countme.bats. Keep state out of layers and reject invalid/future state; compare attempted week under lock and prove file/directory durability before network transmission. Test crash recovery, fsync failure, client/server clock skew and Monday transit; published reports are estimates, not server-week deduplicated identities. Do not ship the timer enabled yet.

**Complexity:** High
**Token estimate:** ~25k
**Agent strategy:** Single implementing agent with independent review; parallel work only when explicitly authorized.

### Phase 1.2: Private collector and public views

New services/countme/ Worker modules, D1 migration, wrangler configuration, dashboard and local-runtime tests. Pin external tooling through image-versions and use dependency lockfiles. Test five UPSERTs as one batch, frozen publication, bounded streaming bodies, pruning, no logging and aggregate health. D1 history can reconstruct category/timing changes; verify restore access/retention and get policy acceptance or use reviewed batching. Separate accepted-report caps from infrastructure invocation/spending limits. Synthetic staging only.

**Complexity:** High
**Token estimate:** ~25k
**Agent strategy:** Single implementing agent with independent review; parallel work only when explicitly authorized.

### Phase 2.1: Every image has the correct category

Justfile:70 original flavor export before scripts/resolve-flavor.sh changes target; scripts/build-image-inner.sh:73-86 build args; new declared args in all six base Containerfiles and Containerfile.overlay. build_scripts/90-image-info.sh:35-55 add separate countme metadata from original variant/full flavor and refresh it in each final desktop/overlay. build_scripts/40-services.sh:150 setup before package-manager early exits, plus after any later shared-copy. New tests/test_countme_contract.py derives coverage via the build-config seam.

**Complexity:** High
**Token estimate:** ~25k
**Agent strategy:** Single implementing agent with independent review; parallel work only when explicitly authorized.

### Phase 2.2: Live media and CI stay outside counts

live-iso/common/src/customize-live.sh:961 runtime-only live exclusion; scripts/iso-e2e.sh and VM launchers set explicit kernel/runtime CI opt-out, never IS_CI baked into production images. Check all other boot harnesses by rg before implementation. New image check under build_scripts/checks/; hook into existing scheduled/PR gates and .github/green-criteria.yml. just build and podman inspection per package-manager family and overlay; installed guest against synthetic collector.

**Complexity:** High
**Token estimate:** ~25k
**Agent strategy:** Single implementing agent with independent review; parallel work only when explicitly authorized.

### Phase 3.1: Reviewed rollout and public adoption history

docs/rfc/rfc012-private-adoption-metrics.md allocated and reviewed under RFC-PROCESS.md; record accepted ADR on decision. New docs/COUNTME.md and installed/installer help with a notice/choice handoff before first request, including upgrades and unattended install policy. Account/hostname owner and total budget selected explicitly. Staging then volunteer pilot with separate storage. Enable final preset only after privacy and all-cell artifact checks plus installed upgrade/switch tests for both opt-out controls and weekly state; keep kill switch and preserve masks. Production deployment is a separate approved operation.

**Complexity:** High
**Token estimate:** ~25k
**Agent strategy:** Single implementing agent with independent review; parallel work only when explicitly authorized.

## Testing Strategy

Phases 1.1/1.2: bats client tests and local Worker database/runtime tests. Phase 2.1: Python matrix-derived contracts and inspection after final image copies. Phase 2.2: real installed/live/CI guests against synthetic collector, failure isolation and opt-out through switch/upgrade. Phase 3.1: explicit manual account privacy review, pilot and public usefulness check. Carry every success metric into the test plan; publication within 24 hours, honest freshness and shared public data.

## Project References

AGENTS.md, docs/AGENT_GUIDE.md, RFC-PROCESS.md, docs/rfc/rfc012-private-adoption-metrics.md, build-config seam and the evidence in research.md.

## Token Management Strategy

Each phase has a separate testable boundary; keep evidence in its own notes and re-read only affected source. Use one implementing agent and independent review; no blanket delegation is assumed.

## Migration Notes

No server event/identifier migration. Existing installs begin reporter-observed age at rollout, never infer a true install epoch. Preserve opt-out and /var state; disable inherited direct reporters without silently changing all distribution analytics. Synthetic staging is separate from production.

## Performance Considerations

One bounded report attempt per week, no boot-critical dependency; five atomic counter writes per accepted report. Closed-week public snapshots may be cached. Total request budget and circuit breaker bound abuse; health records report degradation, not fabricated zero adoption.

## Detailed design from the draft RFC

## Proposed collection contract

One installed-system service sends a small HTTPS POST to a proposed `countme.tunaos.org/v1/report`. The hostname is not provisioned or assumed available. Use POST so image categories do not appear in URL query logs. A fixed user-agent identifies only protocol version.

```json
{
  "schema": 1,
  "variant": "yellowfin",
  "flavor": "gnome-hwe",
  "arch": "x86_64",
  "age_bucket": 2
}
```

Accepted variant/flavor/architecture combinations come from build configuration, with explicit protocol mappings for platform names. No arbitrary free-text dimensions are accepted. Maximum body size is 512 bytes; reject unknown keys, malformed JSON, unsupported schema and non-official combinations. The Worker assigns the current UTC week from server time. Client scheduling uses the client UTC week; clock skew and requests crossing Monday midnight can move or duplicate contributions in a server week. Require time synchronisation before reporting and test clock disagreement and boundary transit. This reduces errors but does not establish exact server-week uniqueness without an identifier. No client timestamp, channel, version, image digest, full OCI reference, game mode or identifier is sent in v1.

Age buckets are 1: first week; 2: weeks 2–4; 3: weeks 5–24; 4: week 25 onward. Age means time since this reporter first observed an eligible installed system, not a proven installation date. Existing installations start in bucket 1 at rollout. State survives upgrades and official image switches; reset or reinstall may restart age.

Never read machine-id to create a payload. Do not send a hash of it, an anonymous UUID, hostname, username, serial, IP, precise age or a local state timestamp. Ordinary TLS transport still exposes the source IP to Cloudflare.

### Client schedule, identity and exclusions

Ship one reporter and systemd service/timer across all base families. Use a persistent daily timer with a random delay, but permit at most one attempted POST per UTC Monday–Sunday week. An eligible run checks exclusions, consent and metadata before touching persistent state. Before transmission, acquire a local lock, compare the existing attempted week while holding that lock, then durably record the attempted week before any network transmission. Atomic replacement alone is insufficient: flush the file and containing directory to stable storage and verify the flush succeeded. Failure to flush means no POST. Choose and test the required filesystem flush tool on every family. Never immediately retry a POST, follow redirects or roll back that marker after a timeout: a lost acknowledgement might already represent a stored report. Limit request runtime to 15 seconds.

This chooses undercount over automatic duplicate reports. If no POST was attempted because eligibility or network preflight failed, a later daily run may try. If a POST fails after the attempt marker, wait until the next week. Record coarse local outcome for support; transmit no history. Reject invalid/future local epoch or attempt state without sending and document recovery; clock rollback must not create another attempt. A power loss after a durable marker but before sending can miss that week's report. Crash tests must also cover a committed remote report and client restart with the attempt marker retained.

Local state holds first-observed epoch and last attempted week in `/var/lib/tunaos-countme`, never in the image layer. A sandboxed oneshot with a dedicated state directory is preferred. Test DynamicUser on every family; do not add privileged `bootc status` access unless runtime identity requires it. The proposed v1 schema deliberately omits stream, avoiding compose-time `latest` masquerading as a runtime channel.

Generate separate immutable countme metadata at build time from the canonical variant and original full requested flavor, before stage resolution changes them. Refresh it in desktop and overlay outputs. Missing or unrecognised identity exits without a request; it must not fall back to GNOME or another variant. Derive coverage and the collector allowlist from the matrix, rather than hand-copying a list into a document.

Require `/run/ostree-booted`, reject container execution, and reject live media through both an explicit live-runtime marker and kernel live flags. Wire the marker into live customization; do not bake the live exclusion into the installed image. CI VM launchers must set an explicit reporting-disable kernel option or runtime marker. Production CI images cannot be disabled just because they were built in CI. A legitimate installed VM counts as an installation.

Disable inherited Project Bluefin/Dakota/LTS reporting units in TunaOS image setup after upstream files are copied. Assert effective masks and preset/link state in the built output, including desktop re-copies and overlays. Existing upstream distribution countme is separate; document its own controls and do not silently claim that disabling TunaOS reporting disables all upstream analytics.

### User control and notice

Draft preference: enabled by default with a simple persistent opt-out. This has not been selected by the user; resolve it before image enablement. Publish the privacy notice before rollout and show the choice in installer documentation and the installed system's help. Gate the first report on completion of an installer/first-boot notice-and-choice handoff, including upgrades of existing installs. The timer remains ineligible until that handoff has made the control available and recorded the chosen policy. Documentation alone is insufficient. Test immediate networking, a persistent overdue timer, unattended installs and upgrades; an unattended policy can explicitly disable reporting.

Proposed opt-out mechanisms:

```sh
sudo install -d -m 0755 /etc/tunaos/countme
sudo touch /etc/tunaos/countme/disabled
sudo systemctl mask --now tunaos-countme.timer tunaos-countme.service
```

Both the reporter and units check the file. The file and masks live in `/etc` and must survive upgrades and switches; never unmask or remove them in a build/first-boot migration. Re-enabling requires the user to remove the file, unmask both units and enable the timer. Keep weekly state on opt-out/re-enable to avoid an extra report. With opt-in instead, require an affirmative local enabled marker and keep the timer disabled until selected.

### Worker and aggregate storage

Use Workers as a strict request boundary and D1 as an aggregate database. Each accepted POST increments a total and four independent margins: variant, full flavor, architecture, age bucket. Store only `(week, dimension, category, count)` with a unique key and integer count. There are no event rows, request times or combined tuples. Execute the five atomic SQL UPSERTs in one D1 transaction/batch; return 204 only after commit. Exceptions return a fixed error with no request data. Do not queue raw reports or copy them to R2.

Workers KV is unsuitable for counter read-modify-write because [its updates are eventually consistent](https://developers.cloudflare.com/kv/concepts/how-kv-works/). D1 [batch calls are transactions](https://developers.cloudflare.com/d1/worker-api/d1-database/); concurrency and rollback must be tested locally in the Worker runtime. Durable Objects are a valid alternative if the collector later needs serialized logic. Neither design needs per-device state.

Disable Workers observability and invocation logs explicitly in all environments. [New Workers have logging enabled by default](https://developers.cloudflare.com/workers/observability/logs/workers-logs/). Do not access request IP headers, geolocation or `request.cf`, log headers/bodies, attach Tail Workers, or enable request Logpush. Inspect account-level HTTP/security logs and log exports before rollout; if applicable logs cannot be disabled or excluded, document their provider retention and revisit hosting. Debug only with synthetic reports, with no real-client request logging.

[D1 Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/) can retain database history. Aggregate-only writes avoid storing identifier fields, but differences between database history states may reconstruct a report's category tuple and timing. They do not guarantee that history contains no event information. Restrict restore/history access to named operators, verify history granularity and retention, and disclose the reconstruction risk before launch. If the approved privacy policy requires no event reconstruction, change to a batched collector with a reviewed minimum batch/release policy before rollout; D1 per-report writes do not meet that stronger requirement. Deletion is not an excuse to store identifier fields briefly. Retain aggregate weeks for a proposed 104 weeks, prune older rows on a daily cron and document backup expiry separately. Keep synthetic staging data outside production.

Unauthenticated anonymous input is vulnerable to fabricated reports. A secret bundled in every image cannot authenticate installs. Use strict allowlists, size limits, aggregate health alarms and a total accepted-report budget with a circuit breaker; calibrate the budget before rollout. Avoid application IP-based rate limits or browser challenges. Denial by a circuit breaker must mark the week degraded. Accepted-report caps bound storage work, not total Worker invocations: rejected traffic still consumes infrastructure. Separately configure account request/spending controls and a shutdown route; verify what Cloudflare plan limits actually enforce, and disclose any edge IP processing if platform abuse controls are selected. These controls do not establish authentic unique installations; public metrics remain estimates.

### Public dashboard and API

Serve a public dashboard and versioned JSON/CSV exports on the same first-party host, with no cookies, third-party scripts or browser analytics. Start with a weekly trend, variant shares, flavor shares, architecture shares and age-cohort shares. Do not offer combined category filters, event downloads or per-device views.

Publish only completed UTC weeks, once per week, from aggregate storage. The current week is labelled collecting with no counts. Each release records methodology version, observation window, generation time and collector availability. Do not invent zero history: prior to rollout is unavailable; an outage is degraded/unavailable; a configured, healthy collection week with no accepted reports may be zero.

Proposed small-group policy: round published counts down to multiples of 10; counts 1–9 are suppressed. If any category in a dimension has a count 1–9, suppress that whole dimension's breakdown for that week, including exports. A total below 10 is also suppressed. This prevents recovering a hidden category by subtracting visible categories from a published total. Do not publish a second exact total or a higher-level rollup that defeats suppression. Release the same frozen values to the dashboard, CSV, JSON and badges; refreshing an API must not reveal incoming events. Review cross-week inference before launch: suppression reduces disclosure but is not a differential-privacy guarantee.

Label the main measure **Weekly reporting installations (estimate)**. Age-cohort changes describe population mix; they do not measure individual retention. Never add weekly values and label the result monthly unique users. Percentages use published values and explain rounding. Suppressed, missing and degraded views have distinct labels.

### Tests and rollout

1. Resolve default participation, hosting ownership, disclosure policy, budget and data retention. Allocate RFC number/tracking issue when publication is authorized; obtain maintainer sign-off and record an ADR when the design is accepted.
2. Implement the local reporter with mocked time/network and temp state. Verify request minimisation, lock races, age/week boundaries, corrupted/future state, clock rollback, lost responses, opt-out and excluded boot modes.
3. Implement the Worker in local Cloudflare runtime. Test concurrent increments, transaction failure, validation/oversized streaming bodies, no request-data logs, aggregate-only storage, pruning and export suppression/inference.
4. Add common image wiring and canonical metadata. Verify script reachability before early exits and effective state after all upstream copies. Add a contract that derives coverage from the configured matrix. Wire declared CI gates into `.github/green-criteria.yml`.
5. Generate artifact identity/unit checks for every official matrix cell, including aliases, all canonical variants and overlay flavors. Build and boot representative real images per package-manager family and an overlay; representative boots supplement the full cell checks. Test installed upgrades and official image switches with both opt-out methods and preserved weekly state. Boot live media and CI guests against a synthetic collector to prove zero reports. Boot an installed guest with networking and verify one request plus correct categorical identity. Rebase and run `just fix && just check`, `just test`, and the required image checks.
6. Deploy a synthetic-only staging collector after approval. Verify DNS/TLS, account logging, state storage and output; configure alerts that use aggregate counts only.
7. Pilot installed reporting with volunteers; keep pilot metrics labelled and separate. Enable all official image cells only after privacy notice and consent/default review. Roll back by disabling the timer, preserving user opt-outs and showing coverage gaps in history.

### Open decisions

- Default-on with opt-out, or opt-in only?
- Which Cloudflare account and operator own the hostname, retention controls and incident response?
- Is weekly publication with suppression at 10 useful for TunaOS's current scale? Suppressed results are preferable to pretending a small population is anonymous.
- Approve 104-week aggregate retention, and confirm backup and provider-log disclosures.
- Which ingestion cap, enforced infrastructure request/spending limit and outage threshold bound cost without silently dropping normal adoption?

The spec and plan are procedurally reviewed by the agent under the unattended-step rule in AGENTS.md. This does not stand in for maintainer RFC approval, authorize cloud deployment, or settle the open participation decision.


## Implementation authorization and working context

On 2026-09-27 the user requested implementation and tests in tunaos and tuna-os/docs, chose enabled by default with persistent opt-out, and identified the domain owner. Wrangler whoami returned unauthenticated. This session provisioned no domain or Worker. Procedural Spektacular reviews are self-approved under AGENTS.md for execution, not RFC approval. Native npm lockfiles pin collector test tools. The client uses Python standard library, DynamicUser state, durable attempt markers and no retries. Public site consumes only frozen aggregate snapshots through its Worker proxy.

### Corral verification limitation (2026-09-27)

Official Corral main `4c59a6be9ea6532aa79c6407bab471b4202c1484` exposes `--file` provisioning on `corral create`, but its KubeVirt builder mounts the raw root partition and invokes `chroot /mnt/root /bin/bash /tmp/provision.sh` without failing the build when that command fails. The script then emits `CORRAL_BUILD_OK`. That does not prove a marker reached the booted deployment. Neither `corral create --bootc` nor `corral bootc create --resume` exposes `--karg` in that source. See [builder](https://github.com/tuna-os/corral/blob/4c59a6be9ea6532aa79c6407bab471b4202c1484/pkg/kubevirt/bootc.go) and [resume command](https://github.com/tuna-os/corral/blob/4c59a6be9ea6532aa79c6407bab471b4202c1484/cmd/corral-bootc/main.go).

`scripts/boot-gate.sh` therefore exits 77 before creating a guest until both fresh and resumed Corral paths expose kernel argument support. With supported capabilities, both receive `--karg tunaos.countme=0`. Stub tests exercise fresh, resume and missing-capability behavior. No Corral guest boot was measured locally; Corral is not installed here. This limitation must not be reported as all-artifact CI exclusion validation.
