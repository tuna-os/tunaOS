---
created_date: "2026-10-18"
document_status: final
closed_date: "2026-10-18"
---

# Single fork config implementation plan

Spec: [20261018194500-single-fork-config-foundation](../../specs/20261018194500-single-fork-config-foundation.md).
Design and milestones: [RFC 013](../../../docs/rfc/rfc013-single-fork-config.md).

## Discovery

Current main uses `.github/build-config.yml`, desktop manifests, package scripts
and brand adapters. Reuse the build-config shell seam and flavor resolver
without changes. The custom overlay is a separate path. PR #3431 proposes
future catalog/identity contracts; it is not merged input.

## Phase 1 implementation

- Add a closed v1 parser and source receipt; retain every catalog field.
- Expand only declared cells and call the existing flavor resolver.
- Merge intent with explicit precedence, stable list order and conflict errors.
- Emit a review plan and a stock-only legacy export. Do not wire consumers.
- Test whole-catalog, expanded-cell, route and source-input parity plus rejection.
- Run the existing Bats resolver/admission checks and aggregate gates.

## Testing and release

Focused tests prove plan/source parity. Effective package operations and image
acceptance remain for phase 2/3. Record actual aggregate failures in the PR.
Keep this PR draft, seek maintainer review and do not merge it. Procedural
prompts are self-approved under AGENTS.md, not RFC sign-off.
