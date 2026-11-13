# ADR 0014: Versioned ISO media provenance contract

- Status: accepted approach for the bounded contract stage
- Date: 2026-10-19
- Approval: [maintainer approach approval](https://github.com/tuna-os/tunaOS/issues/3381#issuecomment-6277491364)
- RFC: [RFC 014](../rfc/rfc014-iso-media-provenance.md)
- Issue: [#3381](https://github.com/tuna-os/tunaOS/issues/3381)

## Context

Browser and native evidence lack a shared final-media identity. Untyped hashes
can confuse the builder with QEMU, or the frontend commit with its bundle.

## Decision

Accept a versioned, typed contract and offline tests first. Bind the final ISO bytes,
source, overlay, frontend and builder to separate browser/native evidence.
Keep independently obtained producer and artifact context outside the receipts.
Keep legacy evidence diagnostic-only. Content identity does not authenticate a
producer; a later collector must verify trusted workflow and artifact context.

## Consequences

- The contract stage changes no production qualification or download policy.
- Tests establish consistency and rejection behavior, not real installation.
- The later collector and adapters need review and actual matching-media proof.
- Plain and encrypted offline installs and target-only reboot remain required.
- Existing downloads and retained objects remain available.

## Follow-on: read-only artifact snapshot adapter

On 2026-10-20, the maintainer approved the adapter and negative tests in
[issue #3381](https://github.com/tuna-os/tunaOS/issues/3381#issuecomment-6280438100).
It checks one selected run of iso-builder CI on main.
It checks the reviewed source, workflow, artifact ID and archive bytes.
It has a read-only transport that the caller supplies, with no production caller.

The first adapter rejects reruns. GitHub binds an artifact to a run but omits
its upload sequence. Before and after collection, the current run must have
`run_attempt: 1` and agree with the selected run endpoint.
This snapshot check depends on fresh authoritative responses.
It does not provide an atomic snapshot or an attestation.
Rerun support needs a separate design that proves the upload sequence.

This phase does not extract archive members, issue credentials, migrate receipt
emitters, or enable qualification. Those integrations still need review and
matching-media installation proof.

## Local proposal: retained media transport in the v2 boundary

The browser producer selects one location for its media. Existing v2 records keep
`artifact.mediaPath` for an ISO inside the selected GitHub archive.
The new `mediaTransport.kind: r2-chunked-candidate` branch omits that member.
Instead, it identifies a manifest in R2 and the whole ISO, with independent review.
Both branches keep the GitHub run, artifact ID, archive digest, receipt path, and
receipt digest. Native evidence keeps its archive branch.

Do not invent an archive member for R2 media. This extension changes the reader,
not the receipt format. Browser `qualification-evidence` and native
`QualificationEvidence/v2` receipts do not change.
Readers for v2 that accept only archives reject the new field under strict validation.
Upgrade those readers before they consume retained candidates.
Do not treat R2 media as an archive member.

The manifest keeps the existing `retained-browser-candidate` schema version 1.
It records storage state, not browser v2 evidence.
Do not relabel diagnostic observations from a producer as a v2 receipt.

`verify_retained_candidate_snapshot` extends the read-only snapshot adapter.
It operates in memory. It needs a policy with independent review.
The caller supplies a transport with fresh, authoritative responses from GitHub.
The caller must also configure the R2 endpoint and bucket to match that policy.
These coordinates contain no credentials.

The verifier does not follow URLs or storage destinations from candidate JSON.
It does not read credentials, connect to storage, write files, or upload objects.
It does not change retention or run an installation.
It uses this bounded sequence:

1. Check the selected successful `workflow_dispatch` on main, with `run_attempt: 1`.
   Check the endpoint for that run sequence, repository IDs, workflow identity,
   and exact source revision.
2. Hash the diagnostic archive and compare it with the API digest and independent
   policy. Accept at most 256 members. Accept at most 16 MiB of declared size
   after decompression, across all members.
   Reject duplicate or unsafe names, symlinks, encryption, and oversized members.
   Read only the selected receipt member, up to 1 MiB, without filesystem extraction.
   Check its independent expected hash, browser role, run, and media coordinates.
   Return the exact receipt bytes to the existing strict v2 boundary.
3. Read at most 1 MiB of combined manifest and provenance data.
   Hash the exact bytes before JSON parse. Compare the hash with the independent
   manifest digest. Check the existing
   `browser-iso/candidates/<run>/<attempt>/yellowfin-gnome/s1/` namespace.
   Check the embedded repository, checkout and workflow revisions, workflow ref,
   job, run, and `runAttempt`. Check that storage is complete, unqualified, and
   has no expiry.
4. Check the order of chunk keys and reject gaps.
   Validate their total size before any chunk read.
   Stream each chunk, up to 64 MiB, and compare its exact size and hash.
   Hash the concatenation and compare it with the independent identity of the
   whole ISO. Keep the caps of 160 chunks and 10 GiB.
   Do not buffer the ISO.
5. Recheck the artifact identity, size, and current run after all byte checks.
   Pass the retained browser producer and exact receipt bytes to
   `check_consistency`. It still needs separate native evidence and independent
   expected context. If the identity of R2 media differs from that context,
   reject it before the large media read.

The tests use tiny synthetic bytes and API responses.
They reject replayed run coordinates, wrong storage origin, and changed manifests.
They reject absent, reordered, or corrupt chunks and the wrong whole-ISO identity.
They reject ZIP members with unsafe metadata, receipt replacement, and changed producer state.
Existing archive fixtures still pass.
These tests do not observe a real retained upload or installation.

### Measured facts versus trusted inputs

- The verifier measures hashes of the raw archive, selected receipt, and manifest.
  It measures sizes and hashes of ordered chunks and of the whole ISO.
  It compares the API data it consumed with policy.
  It also compares the producer coordinates in the manifest with policy.
- Independent trusted inputs select the repository, workflow, source, and first
  run sequence. They supply expected archive, receipt, manifest, and media hashes.
  They also supply the expected ISO size, receipt path, and storage coordinates
  without credentials. Expectations from candidate JSON do not establish trust.
- The adapter must supply fresh, authoritative GitHub JSON.
  It must bind storage keys to its configured R2 endpoint and bucket.
  This module supplies no authenticated transport or atomic snapshot guarantee.
- Actual observations from the browser and engine remain outside this adapter.
  So do immutable source origin from the engine and installed frontend identity.
  Native proof must cover plain and encrypted offline installs of the same media,
  plus target-only reboot. Do not describe requested or catalog values as runtime
  measurements.

Every success continues to say `authentication: not_authenticated`.
Receipt and storage consistency does not authorize qualification, publication,
or cutover.

## Follow-on: bounded authoritative transport caller

The caller in `scripts/iso_authoritative_transport.py` closes the injected
transport gap and does not activate a collector. It accepts reviewer-supplied
policy, explicit run/artifact selection and bounded network policy. It exposes
only the exact endpoints consumed by the existing snapshot validators.

A call that reads GitHub metadata never follows a redirect. The artifact archive can redirect once
from the GitHub API to a reviewed HTTPS origin with an exact match, with the
bearer credential removed. R2 reads use the configured endpoint, bucket and
candidate namespace without that credential or redirects. The limits for connect
time, idle time and total elapsed time apply together with the limits for each
response and for aggregate bytes. Each
read does one socket receive at most, within the remaining total time.

R2 reads need a SigV4 signature from a read-only R2 key. That key is a new
secret and permission, which this change does not add. Until a reviewer
approves a signer, the caller stops the collection of retained media with
`retained_signer_required`. It sends no request.

The validator reads current run, `run_attempt` and artifact metadata before
bytes, then rechecks artifact and run metadata afterward. These sequential REST
and R2 requests are not a transaction. A visible change rejects, but the APIs
cannot establish an atomic snapshot or identify which rerun uploaded an
artifact. The restriction to `run_attempt` 1 remains.

This boundary has no production call site, new permission, admission decision
or catalog effect. A successful HTTPS exchange does not authenticate the
separately reviewed policy or the complete browser/native evidence, so existing
results remain `authentication: not_authenticated`. Runtime integration and
qualification remain gated separately.

## Read-only canonical collection and producer observation handoff

`scripts/iso_canonical_collection.py` is an explicit read-only caller, not an
activated admission service. Its `collect --reviewed-policy FILE` command takes
independent `expectedContext`, `browserPolicy`, `browserSelection`,
`nativePolicy`, `nativeSelection`, and `networkPolicy` objects. Policy and
selection fields are the existing `ReviewedPolicy` and `ArtifactSelection`
dataclass fields; network fields are `ReviewedNetworkPolicy` fields, with
`artifact_redirect_origins` encoded as a JSON array. Neither receipts nor a
catalog may supply this file. A supplied file is not proof that review occurred.

For archive-backed v2 media, collection measures each exact selected GitHub ZIP
into a private temporary file, rechecks artifact and run metadata, reads only the
reviewed receipt/member paths without extracting them, and streams the selected
ISO through the existing v2 consistency check. Both producers retain the
existing approved repository/workflow/main-dispatch/first-successful-attempt
scope. A changed run, changed artifact, swapped raw receipt, unsafe ZIP member,
oversized diagnostic payload, or ISO above **10 GiB** refuses. The collector
bounds ZIP/ZIP64 central directories to 1 MiB and 256 declared and actual
entries before allocation of member objects by the standard library. It
fabricates no archive media member for retained R2 media: that path
still refuses with `retained_signer_required` until a separate, reviewed
decision about the signer exists. The change adds no new signer, secret,
permission, publication, workflow or registry fallback.

`snapshot --reviewed-policy FILE` uses only `browserPolicy`,
`browserSelection`, `networkPolicy`, and optional independently selected
`receiptPath`. It can retain the exact archive digest and legacy receipt digest
of a failed run as a **diagnostic**. It records the unchanged successful-run
validator's before/attempt/after refusal coordinates; it cannot turn that
diagnostic into a passing canonical snapshot. The CLI uses the existing
`gh auth token` credential in memory and never includes it in output.

The finite live collection of run `41388681015`, attempt `1`, artifact
`13119535931` measured the 8,231-byte archive digest
`sha256:517657cf1fd2942a5920f9e355629fbc3b6137693a82ba212268ad7c9e4b311e`.
The initial archive request returned **HTTP 415** because the GitHub REST
endpoint received `Accept: application/octet-stream`. That endpoint now requests
`application/vnd.github+json`; only the separate credential-free artifact
redirect requests binary content. Byte collection then succeeded and retained
the failed-run before/attempt/after `conclusion` refusals and the raw receipt's
`legacy_diagnostic_only` classification. This is a measured transport repair,
not successful install evidence or a reviewed admission-policy claim.

`inspect-browser --measurements FILE --receipt FILE [--observation FILE]`
classifies actual closed-file measurements and raw receipts without converting
legacy evidence into v2. An optional post-close producer envelope has kind
`browser-observed-input`, `schemaVersion: 1`, `qualification: not-assessed`,
an `observed` map containing only available `BrowserObservedInput` fields,
`missingFields` listing every remaining field, the measured `media`, and
diagnostic `measurements`. The fields cannot overlap or silently omit an input.
`finalize_browser_observation` in `iso_media_receipt_handoff.py` accepts only a
complete envelope and delegates to the existing finish/reopen/stable-hash
boundary, then compares the newly measured hash to the producer's observation.
No catalog, requested descriptor, frontend config script, environment pin or
supplied expected context backfills missing consumed input bytes.

`bind_browser_source_observation` takes the existing v2 source descriptor as
independent context. Its third argument maps each exact transport endpoint to
an origin. Neither input can come from the candidate, request or catalog.
There is no default map. The endpoint can be a proxy; it is not the origin.

The function matches the observed endpoint, repository and manifest digest.
It checks OS and architecture from config JSON that the engine consumed and
verified. It also checks the variant against the index and explicit platform.
Absent facts or an unknown map cause refusal, not a requested-value fallback.

The CPU baseline stays a supplied claim from independent context, as RFC014
states. `measurements.sourceBinding.cpuBaselineClaim` records that distinction.
It does not measure hardware support. This step can fill only `source_manifest`;
all other missing fields stay missing. The finalizer still closes and hashes
the media and enforces the 10 GiB cap. No origin map authenticates a producer.

These commands deliberately report `authentication: not_authenticated` and
`qualification: not-assessed`; even a complete byte-consistent pair is
`consistent_not_admitted`. The remaining external admission decision is whether
an independently reviewed collector policy and provenance authority bind these
exact producer workflows/revisions, run/attempts, archive/receipt/media digests,
and measured input descriptors to RFC014 qualification. This implementation
does not supply or replace that decision. Physical byte collection is not
proof of plain/encrypted GUI completion, target-only reboot, cold/warm parity,
performance, or qualification.

Focused behavioral checks:

```sh
pytest -q tests/test_iso_browser_source_binding.py tests/test_iso_canonical_collection.py \
  tests/test_iso_media_receipt_handoff.py tests/test_iso_authoritative_transport.py \
  tests/test_iso_artifact_transport.py tests/test_iso_retained_media_transport.py
```

