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

The retention job can measure two of these rows without the dashboard: stored
bytes and object count. The CI credentials of the job can read these values.
On each scheduled run, `prune-r2.yml` writes an inventory table to its run
summary. The table shows each top-level prefix in the bucket, its object
count, its size, and the retention rule for it. Operation counts and egress
still need the dashboard. The S3 API does not report these values.

The table lists all prefixes in the bucket, not only the two prefixes that
this repository prunes. A prefix without an owner in the table is an open
question for items 2-4 of the issue.

Record the measurement date, billing period, bucket, account, and dashboard
currency/units. Do not infer cost from object count alone: package-repository
syncs can be operation-heavy while ISOs and screenshots are storage-heavy.

## TunaOS write inventory

| Prefix | Writers in this repository | Intended retention | Owner/action |
| --- | --- | --- | --- |
| `live-isos/` | `reusable-build-artifacts.yml`, `publish-iso-groups.yml`, and the variant workflows on their nightly schedule | 14 days for dated objects; `*-latest` objects are live pointers | `prune-r2.yml`; verify the scheduled job is succeeding |
| `screenshots/` | `weekly-desktop-screenshots.yml`, `weekly-qcow2-screenshots.yml`, and installer screenshot jobs | 60 days for dated evidence; `*-latest` objects are live pointers | `prune-r2.yml`; review growth monthly |

The names above are logical prefixes. The configured bucket comes from the
`R2_BUCKET` secret and must be resolved only in the Cloudflare/GitHub settings
that authorized maintainers can access.

The R2 retention workflow is deliberately independent of ISO publishing. A
failed or manually skipped build must not also skip housekeeping. Its dry-run
mode should be used after changing a prefix or age threshold; inspect the
listed deletion set before enabling a destructive run.

### What a variant build writes

Each published ISO cell writes its ISO to `live-isos/` twice: a dated object,
then the `*-latest` pointer. At roughly 6 GB an ISO that is about 12 GB per
cell, and a full matrix for one variant covers about 27 ISO cells. Both copies are
Class A operations, and the dated half stays until `prune-r2.yml` reaches it.

Only the nightly schedule pays that. A `workflow_dispatch` of a variant build
publishes nothing unless someone sets `publish-isos`, because `build-variant.yml`
passes `upload-r2` only for a scheduled run. Before that, `upload-r2` took its
default of true and every test build published a full set. The boot gate runs
before the upload, so a dispatch still builds the ISO, boots it and keeps the
workflow artifact and the e2e evidence.

To publish once, on purpose, use `publish-isos.yml`, which has its own
`skip_upload` input.

## Retention safety rules

- Never delete `*-latest` objects as part of dated-object cleanup; download
  documentation and smoke tests use those stable names.
- Write that rule as `*-latest*`. Do not write a pattern for each extension.
  Non-amd64 ISOs use a different pointer name:
  `<variant>-<flavor>-latest-<arch>.iso` (#1378). The old exclude
  `*-latest.iso*` did not match this name. Thus the prune could delete the
  arm64 pointer and its two sidecars.
  `tests/test_r2_retention_never_deletes_a_latest_pointer.py` reads the pointer
  names from the upload workflows. Then it applies the prune filters to them.
  A new pointer shape gets the same test automatically.
- Keep ISO sidecars (`.sha256` and `.sigstore.json`) with their dated ISO. A
  sidecar without its ISO is not useful evidence or a usable download.
- Prefer a dry run and a bounded age threshold before changing a cleanup job.
- Treat an unknown top-level prefix as an ownership question, not as disposable
  data. Identify its writer and consumer before deleting it.
- A Cloudflare bucket deletion or account-level lifecycle rule needs an
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
