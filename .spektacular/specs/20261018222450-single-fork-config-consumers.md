---
created_date: "2026-10-18"
document_status: final
closed_date: "2026-10-18"
---

# Single fork config consumer preview

## Overview

Continue RFC 013 with a deliberately opt-in local build preview. One pinned file
selects existing desktop cells and feeds package additions, URLs and wallpaper
to both desktop consumer paths without changing normal builds.

## Requirements

- Validate every selected enabled cell before generating any build context.
- Use existing routing, platform/base resolution and catalog holds.
- Copy pinned sources and prevalidated assets into isolated per-cell contexts.
- Share required/optional package additions across five package managers.
- Allow signed RPM repositories; reject unsupported repository semantics and removals.
- Apply URL and wallpaper customization through both desktop entrypoints.
- Keep real config pins strict; initialize new configs explicitly from unpinned templates.

## Constraints

Default builds and source catalog ownership remain unchanged. Reject base/overlay
flavors until their package-phase and parent closure contracts exist. Do not silently
skip unsupported intent. Name/logo need embedded installer/Plymouth integration
and are rejected in this slice. No merge or publication is authorized by this spec.

## Acceptance Criteria

Local executable tests cover inheritance, catalog selection, staged inputs, manager
calls, optional misses, failures and repeat application. Stock consumers no-op
without a payload. A sample fork produces a reviewable build bundle. Actual image,
boot/login/install and visible-art acceptance remain required before rollout.

## Technical Approach

A separate materializer wraps the strict review compiler, copies tracked sources,
and writes a per-cell manifest under the existing manifests context COPY. It calls
the existing build engine only on an explicit build request. All selected cells
must fit the preview subset; held cells remain recorded and never executed.

## Success Metrics

One config fans out supported direct desktop routes without a second variant
catalog, and unsupported operations produce explicit actionable errors.

## Non-Goals

Production CI migration, publication, media generation, generic package removal,
base/overlay parent closure, full name/logo branding and runtime qualification.

## Verification

Run focused Python and executable shell contracts, just fix/check/test and CI.
Report mocks/source contracts separately from actual container/image evidence.
