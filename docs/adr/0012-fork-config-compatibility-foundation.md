# ADR 0012: Fork config compatibility foundation

- Status: proposed; needs maintainer sign-off
- Date: 2026-10-18
- Issue: [#3433](https://github.com/tuna-os/tunaOS/issues/3433)
- RFC: [RFC 013](../rfc/rfc013-single-fork-config.md)
- Implementation: [PR #3434](https://github.com/tuna-os/tunaOS/pull/3434)

## Context

Forks need one owned file for target, package and brand intent. Existing builds
read separate matrix, manifest and brand sources. A whole-build rewrite would
make stock parity hard to verify.

## Proposed decision

Add an opt-in, versioned review contract above existing sources. Reuse the
build-config seam and flavor resolver. Pin the bytes of tracked sources, including
variant overrides and curated experience files. Preserve every disabled cell
and admission record. Export only stock intent to the legacy format.

This phase does not change default builds or integrate package and brand
consumers. It does not approve the later consumer rollout. Accept this decision
only after the maintainer comment required by RFC-PROCESS.md; this proposed
record does not provide that sign-off.

## Consequences

- Forks can validate intent and inspect declared cells without a build.
- Source and route parity do not prove package transactions or built images.
- Later adapters need tests for both desktop paths, generated assets and
  package-family semantics. Test supported-cell build, boot, login and install.
- Rollback keeps the existing build path. No production consumer depends on
  this review command.
