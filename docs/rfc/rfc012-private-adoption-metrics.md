# RFC 012: Private adoption metrics for TunaOS

- Status: The owner approved publication. The agent deployed the collector and dashboard. Images need a source merge before release.
- Issue: [#2775](https://github.com/tuna-os/tunaOS/issues/2775). Owner: `hanthor`.
- Branch: `rfc012-private-adoption-metrics`.
- Scope: all official images on installed systems, across each variant, flavor and architecture.
- Decision record: [ADR 0011](../adr/0011-private-adoption-metrics.md).
- Maintainer instruction (2026-09-27): `please push everything so its deployed and working`.
- The user gave approval for default participation, persistent opt-out and deployment to Cloudflare.
- [Spec](../../.spektacular/specs/20260927065823-privacy-respecting-countme.md).
- [Plan](../../.spektacular/plans/20260927065823-privacy-respecting-countme/plan.md).
- [Detailed design and tests](../../.spektacular/plans/20260927065823-privacy-respecting-countme/context.md#detailed-design-from-the-draft-rfc).

## Purpose

Maintainers and contributors need public adoption trends. Registry pulls include CI, mirrors and updates, so they cannot count installations. A weekly count of reports can show adoption without a device identifier.

The measure will be **Weekly reports from installations (estimate)**. It cannot count each user or show retention for individuals. Offline systems, opt-outs, reinstalls, false reports and network failures affect the result.

## Measured sources

On 2026-09-27, main `7c9efe4f` matched `origin/main`; the commit count between them was `0`. The open PR list had no countme proposal.

- [Dakota client](https://github.com/projectbluefin/common/blob/a9ec4541efa8919581d13f50e800675c5f245a46/system_files/shared/usr/libexec/bluefin-countme): a direct request with image categories and age bucket. State on the client limits requests that succeed to one per UTC week. The daily timer gives offline systems another chance. No device identifier enters its payload.
- [Dakota service](https://github.com/projectbluefin/common/blob/a9ec4541efa8919581d13f50e800675c5f245a46/system_files/shared/usr/lib/systemd/system/bluefin-countme.service): root with a sandbox, to support its `bootc status` fallback. Test `DynamicUser` support before use.
- [Bluefin LTS service](https://github.com/projectbluefin/bluefin-lts/blob/2170146f03de894f13af8d8fd80020ec386e8b01/system_files/usr/lib/systemd/system/bluefin-lts-countme.service): `dnf makecache` for the EPEL metalink. Its comment cites `coreos/rpm-ostree#5464`; the embedded library fails where the CLI works. The timer runs every three days; dnf holds the countme cookie.
- [Dakota PR 807](https://github.com/projectbluefin/common/pull/807): an older proposal for a hash each week. The API returned `closed`, `merged=false`; it did not merge.
- [Universal Blue countme](https://github.com/ublue-os/countme): charts and badges from upstream counts; useful as a public presentation example.

TunaOS now enables `rpm-ostree-countme.service` in two RPM paths. That does not cover all image families. `90-image-info.sh` writes `latest`, and overlay resolution sets the desktop variable to `desktop`. Preserve the original variant and full flavor. These defaults are not categories for adoption.

## Options

| Option | Limit | Decision |
|---|---|---|
| dnf/rpm-ostree countme | Depends on RPM and upstream repos | Separate upstream measure |
| Registry pulls | Counts CI, mirrors and updates | Not adoption |
| Device hash or UUID | Creates linkage and clone-state risks | Reject for v1 |
| Anonymous reports to a normal server | Requires server operation | Valid fallback |
| Anonymous reports to Workers and D1 | Requires review of provider logs and history | Proposed |

## Proposed contract

Use one client across every package manager. Send a bounded HTTPS POST to `countme.tunaos.org/v1/report`. Login through Wrangler authenticated the account that owns the domain. The agent deployed the collector and dashboard. Live health, JSON, browser and accessibility checks passed.

```json
{"schema":1,"variant":"yellowfin","flavor":"gnome-hwe","arch":"x86_64","age_bucket":2}
```

Allow only official category combinations from build configuration. Limit bodies to 512 bytes; reject unknown keys. Use a fixed user-agent. No machine ID, hash, UUID, IP field, user name, hostname, precise age, hardware data, version or channel enters the payload.

Age buckets: first week; weeks 2–4; weeks 5–24; week 25 onward. Age starts when this client first observes an eligible system. At rollout, old installations also start in bucket 1. Preserve state through upgrades and image switches.

A timer runs each day with a random delay. It allows one POST per UTC week on the client. Under a lock, compare the marker for the last request, then flush the new marker and its directory to stable storage before the POST. Do not retry an ambiguous response or follow redirects. A failed request can cause an undercount.

The server assigns the UTC week. Clock skew and midnight transit can move or duplicate reports in a server week. The client needs clock synchronisation. Test these cases. There is no proof of uniqueness in each week on the server.

## Privacy and public output

The Worker validates the request. A D1 transaction increments a total and separate margins for variant, full flavor, architecture and age. No event table, combined tuple, request timestamp or identifier field exists. [D1 batches are transactions](https://developers.cloudflare.com/d1/worker-api/d1-database/); test concurrent updates and rollback.

Publish only after a UTC week ends. Freeze the same values for the dashboard, JSON, CSV and badges. Show missing, degraded, incomplete and suppressed results explicitly. Never add weekly totals and call the sum a count of unique users for a month.

Proposed disclosure policy: round counts down to multiples of 10. Suppress counts of 1–9. If any category in a margin is small, suppress the whole margin to prevent subtraction. No combined filters or live counts. This is not a differential-privacy guarantee.

Cloudflare sees source IPs to serve requests. The application must not read them or geolocation. Disable request logs, log exports and Tail Workers; [new Workers enable logs by default](https://developers.cloudflare.com/workers/observability/logs/workers-logs/). Review security logs at account level and disclose provider retention before launch.

[D1 history](https://developers.cloudflare.com/d1/reference/time-travel/) may reveal category tuples and timing through differences between states. Restrict restore access and confirm retention. If the policy for privacy prohibits that inference, replace per-report database writes with a reviewed batch model before rollout. Tables with aggregates cannot meet that stronger claim alone.

Propose 104 weeks of aggregate history, with hourly deletion of older rows. Document when backups expire. Use distinct storage for synthetic tests and a volunteer pilot.

## User choice and image coverage

On 2026-09-27 the user chose to enable reports by default, with a persistent opt-out. The client ships across official matrix images; live sessions, containers and CI guests do not report. The page explains how to participate or opt out.

Proposed opt-out controls:

```sh
sudo install -d -m 0755 /etc/tunaos/countme
sudo touch /etc/tunaos/countme/disabled
sudo systemctl mask --now tunaos-countme.timer tunaos-countme.service
```

The client and units check the file. Preserve both controls and weekly state through upgrade and image switch. Never clear masks that the user sets. Use `sudo tunaos-countme disable` to set the persistent marker and mask the timer. Use `sudo tunaos-countme enable` to reverse those controls.

Exclude live media, containers, image builds and CI guests with explicit runtime guards. A normal installed VM can count. Do not bake CI exclusion into production images. Disable reporters inherited from Bluefin after all file copies; inspect their effective state in each final image. Analytics from upstream distributions have separate controls.

## Validation and rollout

1. Allocate an RFC number through an issue when publication has authorisation. Resolve participation default, operator, privacy policy, retention and budget; get maintainer sign-off and record the accepted ADR.
2. Test the disabled client and collector with synthetic reports. Cover durable state, clock differences, lost responses, concurrency, validation, logs, database history and public suppression.
3. Derive identity and unit checks for every matrix cell. Boot representative images per package manager and an overlay. Verify both opt-outs and weekly state on installed upgrade and switch paths.
4. Boot live media and CI guests against a synthetic collector; assert zero requests. Collector failures must not block boots, logins, installs or updates. Register new gates in the CI contract.
5. Confirm account controls, DNS/TLS, retention and privacy notice before a volunteer pilot. Separate accepted-report caps from infrastructure request/spend limits: rejected traffic still invokes the Worker.
6. Enable all official image cells only after pilot review. Keep a kill switch and user opt-outs. Publish health and gaps with the history.

The agent completed procedural spec/plan review under the unattended rule in AGENTS.md. The user also gave approval for deployment and requested publication. Full-family installed boot, ARM and upgrade/switch pilot checks remain unmeasured; publication does not claim those checks passed. The API returned HTTP 403 for logs at account level. The agent did not verify controls at account level.
