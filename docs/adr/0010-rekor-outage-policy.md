# ADR 0010: Keep Rekor until an outage crosses an explicit threshold

- Status: accepted
- Date: 2026-09-19
- Issue: [#1750](https://github.com/tuna-os/tunaOS/issues/1750)
- Operational procedure: [Rekor outage response](../../runbooks/rekor-outage.md)

## Context

The 2026-08-14 and 2026-08-15 Rekor incidents made signature publication an
availability risk. In the latter incident, every Albacore flavor built and
passed its gates. Cosign errors stopped promotion because Cosign could not
upload to Rekor.

PR #1748 then reduced the number of Sigstore calls on the promotion path. It
gave each signature operation a 40-minute retry deadline and moved SBOM
attestation off the promotion path. It also added one automatic re-run after 45
minutes.

That recovery path covers a short outage and probably covers an outage of up to
roughly two hours. It does not make Rekor irrelevant: image signing remains a
promotion precondition, and keyless verification depends on Sigstore's
transparency infrastructure.

Availability is not the only consideration. Rekor proves that a signature
using Fulcio's short-lived certificate was made while that certificate was
valid. Removing the log therefore changes the trust model; it is not merely a
backend configuration change.

## Decision

Keep keyless signing with Rekor. A first `SIGSTORE_OUTAGE` is handled by the
existing retry and single automatic re-run. Do not bypass signing, move image
signing off the promotion path, or introduce a long-lived signing key during
an incident.

Reconsider the backend when either trigger is met:

1. **One blocked promotion:** a Sign job exhausts its retry deadline and the
   automatic re-run also exhausts its deadline because Sigstore remains
   unavailable.
2. **Two outage events in a rolling 30 days:** count an event once per workflow
   run, even when several matrix jobs emit `SIGSTORE_OUTAGE`. The original
   attempt and its automatic re-run are one event, not two.

At a trigger, the preferred design to evaluate is **keyless signing with an
RFC 3161 signed timestamp and no transparency-log upload**. This retains
short-lived Fulcio certificates and removes the Rekor dependency that actually
failed. A reliability review and selection of the timestamp authority, consumer
notification, and an atomic migration of image, SBOM, and ISO signing are
required before implementation.

The threshold starts an expedited design and migration; it does not authorize
an unreviewed trust-model change during an outage.

## Options considered

### Long-lived key with transparency-log upload disabled

Cosign supports this, but it moves key storage, rotation, and revocation into
the project. Verification requires distributing the public key and explicitly
ignoring transparency-log verification. A leaked key can also create
signatures without a public log revealing the misuse. This is not the preferred
fallback.

A key pair by itself is **not** a Rekor fallback. `cosign sign --key ...`
still uploads to the transparency log by default. A workflow that changes from
keyless signing to a key but does not explicitly disable tlog upload fails in
the same Rekor outage.

### Keyless signing with RFC 3161 timestamps

This replaces Rekor's evidence that the short-lived certificate was used while
valid with a signed timestamp. It avoids a long-lived project key and removes
the failing Rekor write and read paths. It still gives up public log inclusion,
so verification documentation and security claims must change. Using
`timestamp.sigstore.dev` also retains an operator-level dependency on Sigstore;
an independent or self-hosted authority costs more to operate.

### Publish unsigned and backfill later

Moving image signatures off the critical path would maximize availability, but
would weaken the invariant that a bare flavor tag is never promoted unsigned.
The project keeps that invariant.

## Consequences

- Brief outages remain an operational event, not an emergency architecture
  change.
- Promotion can remain unavailable when both bounded tries fail; that is a
  deliberate fail-closed choice.
- Maintainers must record outage events so the rolling threshold is observable.
- A timestamp migration must cover `reusable-build-image.yml`, SBOM
  attestations, `publish-iso-groups.yml`, and reusable ISO artifact signing.
- Downstream users that pin the current workflow identity or verification
  behavior need advance notice and updated commands.
- `SECURITY.md` and `docs/VERIFY-ARTIFACTS.md` remain accurate until maintainers
  approve and deploy a migration.
