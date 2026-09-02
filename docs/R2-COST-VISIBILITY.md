# Cloudflare R2 cost visibility and retention

This is the maintainer runbook for the TunaOS portion of the shared Cloudflare
R2 bucket. It records what this repository writes, which paths are expected to
be retained, and the measurements to capture from Cloudflare. It intentionally
does not contain bucket names, endpoints, access keys, or guessed prices.

Issue: [#1618](https://github.com/tuna-os/tunaos/issues/1618)

## Monthly visibility check

An organization owner with Cloudflare billing access should record these values
for the previous calendar month, then attach the export or dashboard link to
the issue or the operations log:

| Metric | Cloudflare source | Required breakdown |
| --- | --- | --- |
| Stored data, GB-month | R2 dashboard → Storage | bucket, then `live-isos/` and `screenshots/` where available |
| Class A operations | R2 dashboard → Operations | PUT/COPY, LIST, and DELETE; identify the largest producer |
| Class B operations | R2 dashboard → Operations | GET/HEAD; separate public downloads from CI reads if available |
| Egress | R2 dashboard → Egress | confirm the R2 free-egress assumption for the account and traffic path |
| Object count | R2 usage or an authenticated inventory | `live-isos/`, `screenshots/`, and any unexpected top-level prefix |

Record the measurement date, billing period, bucket, account, and dashboard
currency/units. Do not infer cost from object count alone: package-repository
syncs can be operation-heavy while ISOs and screenshots are storage-heavy.

## TunaOS write inventory

| Prefix | Writers in this repository | Intended retention | Owner/action |
| --- | --- | --- | --- |
| `live-isos/` | `reusable-build-artifacts.yml`, `publish-iso-groups.yml`, and the variant workflows | 14 days for dated objects; `*-latest` objects are live pointers | `prune-r2.yml`; verify the scheduled job is succeeding |
| `screenshots/` | `weekly-desktop-screenshots.yml`, `weekly-qcow2-screenshots.yml`, and installer screenshot jobs | 60 days for dated evidence; `*-latest` objects are live pointers | `prune-r2.yml`; review growth monthly |

The names above are logical prefixes. The configured bucket comes from the
`R2_BUCKET` secret and must be resolved only in the Cloudflare/GitHub settings
that authorized maintainers can access.

The R2 retention workflow is deliberately independent of ISO publishing. A
failed or manually skipped build must not also skip housekeeping. Its dry-run
mode should be used after changing a prefix or age threshold; inspect the
listed deletion set before enabling a destructive run.

## Retention safety rules

- Never delete `*-latest` objects as part of dated-object cleanup; download
  documentation and smoke tests use those stable names.
- Keep ISO sidecars (`.sha256` and `.sigstore.json`) with their dated ISO. A
  sidecar without its ISO is not useful evidence or a usable download.
- Prefer a dry run and a bounded age threshold before changing a cleanup job.
- Treat an unknown top-level prefix as an ownership question, not as disposable
  data. Identify its writer and consumer before deleting it.
- A Cloudflare bucket deletion or account-level lifecycle rule requires an
  owner with dashboard access; this repository cannot prove that `tunaosdev`
  is unused or safely delete it.

## Follow-up outside this repository

This runbook covers only TunaOS workflows. The same inventory must be completed
for `tunaos-packages`, `tromso`, `xfce-linux`, and the tacklebox repositories.
In particular, package-repository `rclone sync` calls should be compared by
Class A operation volume before anyone changes the distribution architecture.
Provider migration is a separate decision and should not be proposed from
storage estimates alone; retention and operation patterns must be measured
first.
