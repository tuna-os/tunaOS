# Architecture Decision Records (ADRs)

This directory contains the durable Architecture Decision Records for tunaOS.

ADRs document significant architectural and process decisions made throughout the project's evolution, capturing context, rationale, trade-offs, and consequences.

## Lifecycle & Governance

The ADR process is governed by [RFC-PROCESS.md](../../RFC-PROCESS.md) (established in [ADR 0004](0004-rfc-lifecycle.md) and tracking [#1093](https://github.com/tuna-os/tunaOS/issues/1093) / [#1094](https://github.com/tuna-os/tunaOS/issues/1094)).

When an architectural change, significant refactoring, or policy is adopted:
1. An RFC is drafted and reviewed per [RFC-PROCESS.md](../../RFC-PROCESS.md).
2. Upon maintainer sign-off and merge, an ADR is recorded in `docs/adr/` with the format `NNNN-short-title.md`.
3. Historical decisions are backfilled as needed to ensure decision transparency.

## ADR Index

| ADR | Title | Status | Date | Tracking / Context |
|---|---|---|---|---|
| [0001](0001-gdx-to-nvidia-rename.md) | Rename GDX flavor to NVIDIA | Accepted | 2026-06 | Suffix clarity (`-gdx` → `-nvidia`) |
| [0002](0002-browser-iso-builder.md) | In-browser ISO builder with zero-publish architecture | Accepted | 2026-08 | [#667](https://github.com/tuna-os/tunaOS/issues/667), [#1203](https://github.com/tuna-os/tunaOS/issues/1203) |
| [0003](0003-mkosi-co-build-poc.md) | mkosi unified image co-build investigation and PoC | Recorded | 2026-08-11 | [#999](https://github.com/tuna-os/tunaOS/issues/999) |
| [0004](0004-rfc-lifecycle.md) | RFC lifecycle policy (RFC-PROCESS.md) | Accepted | 2026-08-11 | [#1093](https://github.com/tuna-os/tunaOS/issues/1093), [#1094](https://github.com/tuna-os/tunaOS/issues/1094) |
| [0005](0005-flavor-equality.md) | Flavor equality, no primary desktop tier | Accepted | 2026-08-11 | [#1315](https://github.com/tuna-os/tunaOS/issues/1315), [#1316](https://github.com/tuna-os/tunaOS/issues/1316) |
| [0006](0006-date-based-versioning.md) | Date-based versioning + stability tiers | Accepted | 2026-08-13 | [VERSIONING.md](../../VERSIONING.md), [#274](https://github.com/tuna-os/tunaOS/issues/274) |
| [0007](0007-registry-mirror-support.md) | Registry mirror support & fallback architecture | Accepted | 2026-08-13 | RFC-009, `registry-map.yaml` |
| [0008](0008-shell-python-boundary.md) | Where shell ends and Python begins | Accepted | 2026-08-14 | [#1651](https://github.com/tuna-os/tunaOS/issues/1651) |
