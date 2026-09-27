# TunaOS countme collector

The Worker accepts anonymous categorical reports and publishes closed UTC weeks.
It stores five independent counters per report: total, variant, flavor,
architecture and age bucket. It has no event, device or combined-category table.

## Local validation

```sh
cd services/countme
npm ci --ignore-scripts
npm test
npm run build
WRANGLER_SEND_METRICS=false npx wrangler deploy --dry-run
```

Tests use Miniflare's real D1 implementation. They cover concurrent writes,
transaction rollback, body limits, category validation, suppression, snapshots,
clock boundaries, health gaps and retention. The generated allowlist comes from
`.github/build-config.yml`; run `scripts/generate-countme-allowlist.py` from the
repository root after matrix changes.

The deployment review also tests the collector with the website source. With a
sibling checkout of `tuna-os/docs`, run:

```sh
npm run test:site
# For another checkout location:
TUNAOS_DOCS_SOURCE=/path/to/docs npm run test:site
```

This test passes real D1 snapshots through the website proxy and validator. It
checks the application fetch call for copied visitor headers and query strings.
Cloudflare can add transport headers; the test does not exercise provider HTTP
transport or establish provider-level anonymity.

## Deployment

The production configuration binds the dedicated `tunaos-countme` D1 database
and enables collection at `countme.tunaos.org`. For a new environment, disable
collection first, create a separate D1 instance, set its database ID, apply
migrations, and attach the reviewed hostname before enabling collection. Use separate instances for tests,
pilot and production. Before launch, verify provider logs, retention, budget and the user notice.
The hostname is configured as a Worker custom domain. Authenticate with
`wrangler login` as the tunaos.org domain owner before the commands below.

```sh
WRANGLER_SEND_METRICS=false npx wrangler d1 create tunaos-countme
WRANGLER_SEND_METRICS=false npx wrangler d1 migrations apply tunaos-countme --remote
WRANGLER_SEND_METRICS=false npx wrangler deploy
```

Set `COLLECTION_ENABLED` to `true` only after that review. Set it to `false` to
stop accepted reports. `WEEKLY_REPORT_CAP` bounds accepted reports per UTC week;
atomic admission rejects further reports with HTTP 429 and marks that week degraded. Rejected requests still
invoke the Worker and can incur costs. Configure account request/spend limits
and edge protections separately. No per-IP limit or identifier is implemented.
Unauthenticated reports can be forged; the cap does not prove unique systems.

## Public interfaces

- `POST /v1/report`: bounded 512-byte JSON, exact schema, official combinations.
- `GET /v1/metrics`: JSON snapshots for at most 104 closed UTC weeks.
- `GET /v1/metrics.csv`: CSV from the same snapshots, with the same suppression.
- `GET /health`: database availability and the collection switch, without counts.

No endpoint exposes the current week, raw state, category filters or tuples.
Counts round down to tens. Totals from one to nine are suppressed. A margin with
any category from one to nine is suppressed in full. Snapshots are immutable;
JSON and CSV cannot reveal smaller groups by changing the export. This policy
is not differential privacy. Weekly counts cannot measure unique monthly users.

The hourly cron persists one sample per UTC hour. A week with all 168 samples
is labelled `complete`; partial samples mean `degraded`; no samples mean
`unavailable` and null counts. This measures scheduled database access, not
continuous API availability. A first partial week is degraded. Disabled periods
and outages leave gaps. Failed publication leaves stale snapshots; consumers
must check the latest week. Zero is published only for a week with health samples.
The cron deletes counters, heartbeats and snapshots older than 104 weeks.

## Privacy boundary

The application does not inspect IP headers, Cloudflare request metadata,
location or user-agent. It does not log requests or store raw queues. Worker
observability, invocation logs, previews and workers.dev are disabled in the
configuration. Before launch, verify those effective account settings and also
check Tail Workers, Logpush, security logs and provider retention. Cloudflare
processes source IP addresses to transport requests; application controls cannot
remove that provider processing.

D1 Time Travel and operator access are a separate privacy boundary. Differences
between successive database versions can reconstruct the category tuple and
approximate timing of a report, despite aggregate-only tables. Restrict restore
and database access, record provider history retention in the public notice,
and confirm when deleted data expires from backups. Cloudflare automatically
retains recovery history for up to 30 days (7 days on the Workers Free plan). The 104-week SQL deletion
policy does not erase retained database history. If this inference is outside
the accepted policy, do not enable this collector; use a reviewed batching model.

References: [D1 atomic batches](https://developers.cloudflare.com/d1/worker-api/d1-database/),
[Worker logs](https://developers.cloudflare.com/workers/observability/logs/workers-logs/),
[D1 Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/).
