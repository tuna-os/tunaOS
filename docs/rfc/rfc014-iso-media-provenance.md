# RFC 014: ISO media provenance

- Status: contract stage merged; read-only adapter under review
- Owner: hanthor
- Branch: rfc014-iso-media-provenance
- Tracks: [#3381](https://github.com/tuna-os/tunaOS/issues/3381), [#3470](https://github.com/tuna-os/tunaOS/issues/3470), [iso-builder#270](https://github.com/tuna-os/iso-builder/issues/270)
- Proposal: [media identity handoff](https://github.com/tuna-os/iso-builder/issues/270#issuecomment-6277123450)
- Approval: [bounded approach](https://github.com/tuna-os/tunaOS/issues/3381#issuecomment-6277491364)
- Decision: [ADR 0014](../adr/0014-iso-media-provenance-contract.md)

## Problem

Evidence from a browser build differs from evidence of a native install.
Their current v1 formats do not bind those stages to the same final ISO bytes.
A source image, overlay, installer bundle, deployed frontend, builder and test
harness can each have a valid hash. The hashes have different meanings.

## Decision

Define a v2 contract with separate browser and native roles. Add an offline
checker and common test vectors first. Keep v1 records readable as diagnostics.
The v2 contract rejects missing, unknown and old versions.

The first stage has no production caller. A valid document or consistent pair
is not enough to qualify a target. Keep downloads and publication policy unchanged until all gates pass.
Those gates must check authenticated evidence and proof from tests in a real system.

## Identity and order

1. Resolve the OCI manifest for the source platform and the overlay before the build.
   Record platform, CPU baseline and overlay base identity.
2. Measure the deployed Flatpak frontend: application, ref, architecture and
   deployed commit. Record the bytes of a bundle separately when one exists.
3. Identify the WASM builder module, its source revision and runtime shim.
   Neither a QEMU binary nor a harness for native tests can identify the builder.
4. Hash the final closed ISO and record its byte size in an external receipt.
   Never put an ISO hash inside the ISO or an overlay hash inside that overlay.
5. Upload the media and receipt. Keep the artifact ID and archive hash in
   independently obtained context. They cannot be part of a self-hashed archive.
6. Native tests verify the selected archive and ISO bytes before boot. Their
   receipt names the exact browser receipt and keeps the identity of the harness separate.

Bare `linux/amd64` does not determine a CPU baseline. Keep the supplied baseline
and match it against independent context. The initial supported set is x86-64,
x86-64-v2, x86-64-v3 and armv8-a. A platform with an explicit variant limits the set.

The fixture has values from the catalog. It does not prove runtime support.
Refresh it manually from a reviewed snapshot; it does not monitor another repository.

Both plain and encrypted native observations must identify the source and
installed system. They must record completion through the GUI offline and reboot from the target alone.
These facts cannot come from a skipped step, an absent field or a claim of success.

## Trust boundary

A hash identifies the content of bytes. They do not authenticate a producer.
A later collector must get facts about artifacts and runs independently, against
maintainer-reviewed configuration that pins the workflow definition and source.
An untrusted pull request or receipt cannot authorize its own workflow.

Give the offline checker its expected context as a separate argument. It checks
consistency with that context; it cannot prove how a caller obtained the context.
Production admission must never accept a context supplied by the candidate.
The policy for release signatures remains in [#1187](https://github.com/tuna-os/tunaOS/issues/1187).

## Browser resources

Each observation identifies its subject, quantity, unit, source and method. Keep measured,
reported and estimated values distinct. Browser memory reports do not establish
physical RAM. An estimate of storage does not guarantee space on the disk.
Reject profiles that are unknown, units that are invalid and prerequisite values that are non-finite.

## Alternatives

- Extend v1 without a new version: rejected. A deployed commit differs from a
  bundle hash. The v1 format also differs between browser and native roles.
- Import all infrastructure from the open #3431: rejected for this stage. The pure
  contract can land on main without catalog or workflow integration.
- Use schema checks alone: insufficient for equality across exact byte streams
  and independently obtained context. Use behavioral checks as well.

## Delivery and remaining work

This stage provides a schema, offline validation and synthetic test vectors.
Fixtures stay under tests and cannot enter published catalogs. Later work must
connect the real browser producer, exact artifact transport, native harness and
trusted collector. It must pass offline plain/encrypted install and target-only
reboot on the same media before per-target qualification or cutover.

This stage deletes no retained objects. No new publication stream, credentials or
workflow permissions are part of this stage. Spektacular procedural review uses
the self-approval rule in AGENTS.md; it does not expand maintainer approval.

## Read-only artifact snapshot phase

Select one artifact for the adapter to check.
Its policy names the reviewed repository ID, workflow ID and path, source
commit, branch, expected archive digest and byte limit. A receipt cannot supply
that policy. The first producer scope is `tuna-os/iso-builder`,
`.github/workflows/ci.yml`, `refs/heads/main`, with a successful manual run.

Supply fresh responses from the API and archive bytes through a read-only
interface. It constructs exact endpoints for the run and artifact.
It never selects by latest success, artifact name or candidate URL.
It checks metadata before archive access and hashes bytes within the limit.
Then it checks the artifact and current run again.

Both run observations must have `run_attempt: 1`.
The adapter rejects reruns because the artifact API omits the upload sequence.
Timestamps cannot prove that sequence. Assertions in receipts cannot prove it.
A later rerun does not change the identity of bytes already checked.
REST does not promise an atomic view across these requests.

Successful output reports metadata and archive checks with
`authentication: not_authenticated` and `attempt_policy: first_attempt_only`.
The measured byte length must match the API artifact size and the independent limit.
The [uploader](https://github.com/actions/toolkit/blob/main/packages/artifact/src/internal/upload/upload-artifact.ts)
records the size and digest of uploaded bytes.
It checks artifact identity, size and expiration again after the hash.

The result is not a v2 pair of transport records.
It does not fabricate a native producer, interpret a receipt or qualify media.
The caller must provide fresh, authenticated transport and reviewed configuration.
That future caller must also enforce safe redirects and timeouts.
This phase has no network client or production caller.

Fixtures record the reviewed source and use synthetic run and artifact IDs.
They cannot prove a browser build. The existing producer emits records in v1,
which remain outside v2 admission.

## Diagnostic receipt construction and handoff

`scripts/iso_media_receipt_handoff.py` defines the offline boundary between
observed browser/native results and the existing v2 documents. It constructs
receipt bytes only. Every returned candidate has `qualification: not-assessed`;
it creates no producer context, archive identity, admission result, publication,
or storage write.

The browser interface accepts distinct observations for the source platform
manifest and CPU baseline, overlay and base, deployed frontend commit and
optional bundle, loaded WASM/source/shim, browser resources, request/config
digests, and producer run. It has no catalog or request fallback. The selected
operation must still be the completed operation. The adapter then calls the
media sink's `finish()` itself. Only after that save and close succeeds does it
take a stability token, reopen the closed bytes, stream their exact hash and
size, close the reader, and confirm that the token did not change. An
incomplete build, stale selection, failed write/close, byte-count mismatch, or
changed saved object emits no receipt.

The returned browser candidate contains the exact canonical receipt bytes,
their external hash, the measured media identity, and the operation handoff ID.
A retention caller may persist that diagnostic candidate immediately, before a
guest harness runs. Retention therefore does not depend on a failing guest
harness becoming successful. This interface does not add a retention backend or
enable publication.

The native interface accepts the raw browser receipt bytes, the browser receipt
hash and run actually observed by the harness, the media identity measured
before boot, the separate native harness/run identity, and explicit plain and
encrypted results. It re-parses the raw browser bytes with duplicate-key
rejection, checks the browser role/run/hash, and remeasures the exact supplied
media. Each mode's source digest must equal the source digest in the bound
browser receipt. Each mode must also report a completed offline GUI install,
matching installed identity, target-only completed boot, and a passing desktop
contract. Backend,
partial, skipped, online, installation-media, and fixture results fail closed.
Only then does it emit native v2 receipt bytes that name the exact raw browser
receipt hash.

These candidates feed the existing schema and `check_consistency` boundary.
They remain diagnostics until the authoritative caller in #3795 supplies
independently trusted transport/context and real same-media gates pass. Actual
browser integration, native execution, authentication, qualification, and
cutover remain separate work.
