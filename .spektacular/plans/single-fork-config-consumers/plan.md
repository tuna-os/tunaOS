---
created_date: "2026-10-18"
document_status: final
closed_date: "2026-10-18"
---

# Single fork config consumer preview

Spec: ../../specs/20261018222450-single-fork-config-consumers.md

## Architecture and components

Keep resolve-fork-config.py as the strict review-only schema/receipt authority.
Add prepare-fork-config.py as an explicit local build preview; no default workflow
migration. Validate every selected enabled direct desktop route before output.
Use resolve-flavor.sh and get-base-image.sh, not a variant catalog copy. Reject
base/overlay routes requiring parent closure. Retain intentional upstream mutable
base tags with an explicit warning and provenance flag, never claim they pin bytes.

Copy tracked inputs into isolated per-cell contexts, compare source receipts,
then add manifests/fork-config.json and content-addressed JPEG assets. Existing
Containerfiles already COPY manifests. Build via build-image-inner.sh only on
--build; include fork payload/asset hashes in its bind-mount cache key. Each
platform gets a distinct local tag. Disable fork layer reuse with --no-cache
until every legacy stage has cache evidence. Never push or create publication artifacts.

## Data and safety

The closed manifest contains schema_version, variant, flavor, platform,
package_manager, image, intent, sources.sha256 and assets. Source receipt and review
plan remain alongside the bundle. Five native package-manager wrappers consume
required/optional adds. Reject options/archive specs, all removals, and non-RPM
repositories. Signed RPM metadata and package checks are mandatory. Save a
completed manifest-hash receipt with optional misses; repeat dual-path calls
are no-ops only for the exact completed manifest.

Brand helpers accept homepage/documentation/support and validated JPEG wallpaper.
Reject name/logo until installer embedded resources and Plymouth can be adapted.
Run validation before mutation, then apply through 90-image-info and both desktop
entrypoints after stock art selection. Keep stock branding checks and adapt only
the supported URL expectations when validated fork metadata is present.

## Templates and dependencies

An explicit --init-template command adds a current source pin only to templates
without catalog. It never refreshes an existing pin. Tests initialize fresh
stock configs; committed examples are templates instead of constantly stale
reviewed source claims. PyYAML is an existing host dependency; Pillow is required
only for optional wallpaper decode. Normal builds gain neither Python dependency.

## Testing and milestones

1. Strict preflight, sample two-variant fanout and source-copy/hold contracts.
2. Executed package adapter tests, failures, optional misses and repeated calls.
3. Executed brand helper tests and hooks on both desktop paths.
4. just fix/check/test, exact-head CI and draft PR review.

Mocked manager dispatch and temporary-root tests are not evidence that a package
exists in a live repository or that an image boots. Canary images per family
and desktop, login/install and screenshots remain rollout gates. No merge before
maintainer approval. Procedural confirmations self-approved under AGENTS.md.

## Open questions / next slices

Solver-backed removal protections, base/overlay closure, non-RPM repository
schema, embedded installer/name/logo/Plymouth generation, production fanout and
canary qualification remain out of scope for this preview.
