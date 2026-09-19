# Respond to a Rekor outage

## Recognize the incident

The signing retry helper emits this stable marker when its 40-minute deadline
is exhausted:

```text
::error::SIGSTORE_OUTAGE: cosign still failing after 40m of Sigstore unavailability; giving up.
```

Confirm that the underlying error names a Sigstore endpoint and an availability
failure, for example:

```text
Post "https://rekor.sigstore.dev/api/v1/log/entries": status 502: 502 Bad Gateway
```

Check both the endpoint and Sigstore's status page:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://rekor.sigstore.dev/api/v1/log
```

- <https://status.sigstore.dev>

A GHCR failure is a different incident. `.github/scripts/cosign-retry.sh`
retries only errors that name a Sigstore endpoint and match a transient status
or network failure.

## Immediate response

1. Do not disable signing or change keys during the outage.
2. Let `rerun-infra-failures.yml` classify the marker, wait 45 minutes, and
   re-run the failed jobs once.
3. Check the same Actions run after the re-run. Confirm whether its Sign job
   succeeded and its Promote jobs ran.
4. Record the event in the incident or tracking issue using the table below.
   One workflow run is one event even if many matrix jobs failed. Its re-run is
   part of the same event.

```markdown
| First attempt (UTC) | Workflow run | Affected Sign jobs | Re-run result | Promotion blocked? |
|---|---|---:|---|---|
| YYYY-MM-DD HH:MM | URL | N | recovered / SIGSTORE_OUTAGE | yes / no |
```

Use the marker, not a red run alone, as evidence. Preserve links to both failed
job logs because Actions logs eventually expire.

## Decision thresholds

Follow [ADR 0010](../docs/adr/0010-rekor-outage-policy.md):

- escalate after **one event that also fails its automatic re-run and blocks
  promotion**; or
- escalate after **two events in a rolling 30-day window**, including events
  whose automatic re-run recovered.

For the rolling count, use the first attempt's completion time. Count a run
once, not once per flavor, platform, failed job, or attempt. This prevents one
Rekor incident from looking like dozens of independent outages while still
making a second incident visible.

## If the threshold is crossed

Open or update the signing-backend tracking issue and include:

- the event table for the preceding 30 days;
- links to the original and automatic re-run Sign jobs;
- whether existing-image verification was also unavailable;
- Sigstore's incident report or status history, when available; and
- which image, SBOM, and ISO publishing paths were affected.

Evaluate keyless signing with RFC 3161 timestamps first. Do not merge a partial
migration: image signatures, SBOM attestations, grouped ISO signing, reusable
artifact signing, verification commands, and `SECURITY.md` must tell one
consistent trust story. Choose and review the timestamp authority before
adding Cosign flags.

Do not treat `cosign sign --key ...` as a Rekor workaround. Cosign uploads
key-based signatures to the transparency log by default unless tlog upload is
explicitly disabled, so that change alone preserves the outage dependency
while adding long-lived-key risk.
