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
