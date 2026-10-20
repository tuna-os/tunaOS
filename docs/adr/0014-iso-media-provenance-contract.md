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

The browser producer has two mutually exclusive media locations. Existing v2
records retain `artifact.mediaPath` for an ISO inside the selected GitHub archive.
The additional `mediaTransport.kind: r2-chunked-candidate` branch omits that member
and identifies an independently reviewed R2 manifest and whole ISO instead.
Both branches retain the GitHub run, artifact ID, archive digest, exact receipt
path, and receipt digest. Native evidence remains on its existing archive branch.
No archive member is invented to represent R2 media.

This is an additive reader extension, not a new receipt format. Browser
`qualification-evidence` and native `QualificationEvidence/v2` receipts do not
change. Archive-only v2 readers reject the new field under their existing strict
validation; they must be upgraded before consuming retained candidates. Never
silently downgrade R2 media to an archive member. The retained manifest continues
to use the existing `retained-browser-candidate` schema version 1; it is a storage
record, not a browser v2 receipt. Existing diagnostic producer observations cannot
be relabeled as a v2 receipt.

`verify_retained_candidate_snapshot` is an in-memory, read-only extension to the
existing snapshot adapter. It requires independently reviewed policy and a caller
transport with fresh authoritative GitHub responses plus explicitly configured R2
endpoint/bucket. Those non-credential coordinates must match policy; no URL or
storage destination from candidate JSON is followed. The verifier does not read
credentials, connect to storage, write files, upload, change retention, or run an
installation. Its bounded sequence is:

1. Check the selected successful `workflow_dispatch` on main, attempt one, the
   attempt endpoint, repository IDs, workflow identity and exact source revision.
2. Hash the bounded diagnostic archive against the API and independent policy;
   accept at most 256 members with at most 16 MiB total declared uncompressed
   size. Reject duplicate/unsafe names, symlinks, encryption, and oversized members.
   Read only the exact selected receipt member (at most 1 MiB), with no filesystem
   extraction, and check its independently expected hash and browser/run/media
   coordinates. Return its exact bytes to the existing strict v2 boundary.
3. Read at most 1 MiB of combined manifest/provenance, hash the exact bytes before
   JSON parsing, and require the independent manifest digest. Check the existing
   `browser-iso/candidates/<run>/<attempt>/yellowfin-gnome/s1/` namespace and
   embedded producer repository, checkout/workflow revision, workflow ref, job,
   run and attempt. Require complete, unqualified, no-expiry storage state.
4. Validate ordered, contiguous chunk keys and their aggregate size before any
   chunk read. Stream each chunk (at most 64 MiB), compare its exact size and hash,
   and hash the concatenation against the independent whole-ISO identity. The
   existing caps remain 160 chunks and 10 GiB; the verifier does not buffer the ISO.
5. Recheck artifact identity/size and the current run after all byte checks. Pass
   the retained browser producer and exact receipt bytes to `check_consistency`,
   which still requires separate native evidence and independently expected
   context. An R2 media identity that differs from that context fails before the
   potentially large media read.

The tests use tiny synthetic bytes and API responses. They establish rejection
behavior for replayed run coordinates, wrong storage origin, changed manifest,
missing/reordered/corrupt chunks, wrong whole-ISO identity, unsafe ZIP members,
receipt replacement, and changed producer state. Existing archive fixtures still
pass. These are not observations of a real retained upload or installation.

### Measured facts versus trusted inputs

- Measured by this verifier: raw archive, selected receipt and manifest digests;
  ordered chunk sizes/digests; aggregate ISO digest/size; equality of consumed
  API and embedded producer coordinates to policy.
- Independent trusted inputs: reviewed repository/workflow/source/first-attempt
  selection, expected archive/receipt/manifest/media hashes, expected ISO size,
  receipt path, and non-credential storage coordinates. Copying expectations
  from candidate JSON does not establish trust.
- Conditional adapter inputs: GitHub JSON freshness and authority, and the
  adapter's binding of storage keys to its configured R2 endpoint/bucket. This
  module supplies no authenticated transport or atomic snapshot guarantee.
- Still outside this adapter: actual browser/engine observations, immutable
  engine-observed source origin, installed frontend identity, and matching-media
  native plain/encrypted offline installation and target-only reboot. Requested
  or catalog values must not be described as measured runtime observations.

Every success continues to say `authentication: not_authenticated`. Receipt and
storage consistency does not authorize qualification, publication, or cutover.
