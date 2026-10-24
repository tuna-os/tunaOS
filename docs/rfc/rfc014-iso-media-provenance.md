# RFC 014: ISO media provenance

- Status: contract stage merged; bounded read-only caller under review
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

The initial contract stage had no network caller. A valid document, consistent
pair or successful HTTP exchange is not enough to qualify a target. Keep
downloads and publication policy unchanged until all gates pass.
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

`scripts/iso_authoritative_transport.py` supplies the bounded read-only caller.
It accepts the reviewed policy and selected IDs as separate arguments.
It permits only the exact run, first-attempt, artifact and archive paths that the
existing validators construct. It never lists runs, selects the latest success,
accepts a candidate URL or infers an upload attempt from timestamps.

The caller sends the GitHub bearer credential only to `https://api.github.com`.
An artifact download may redirect once to an exact origin in reviewed network
policy; the redirected request has no credential. Retained-object requests use
only the configured R2 endpoint, bucket and exact candidate namespace. They
never receive the GitHub credential and cannot redirect.

Reviewed limits bound connect, idle and total elapsed time, each JSON response,
each archive or object response, and aggregate response bytes. The existing
validators still enforce exact expected sizes and digests. Every response is
closed after success or failure. Synthetic HTTP-server tests exercise these
limits and origin rules without a credential or production request.

This caller does not make the REST and R2 observations atomic. GitHub exposes
no artifact upload-attempt identity, so first-attempt-only remains mandatory.
The validators compare metadata before and after all byte reads and reject a
visible change, but an API cannot prove that no transient change occurred
between sequential requests.

Endpoint authentication does not attest the separately reviewed policy or
qualify browser/native evidence. Successful results therefore remain
`authentication: not_authenticated` and contain no admission decision.
There is no production call site, workflow permission change or catalog wiring.
The exact-media receipt handoff and runtime integration/qualification gates
remain separate work under #3796, #3797 and #3381.

Fixtures record the reviewed source and use synthetic run and artifact IDs.
They cannot prove a browser build. The existing producer emits records in v1,
which remain outside v2 admission.
