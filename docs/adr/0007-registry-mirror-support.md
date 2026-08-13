# ADR 0007: Centralized registry-map.yaml + registry_ref() for mirrorable image references

- Status: accepted (shipped directly to main, not via the rfc009-registry-mirrors-* branches)
- Date: 2026-06-07 (Phase 1), phases through 2026-07-06
- Last updated: 2026-08-13
- Design doc: RFC-009 (see `registry-map.yaml`'s own header: "See RFC-009 for
  design rationale") — the design was never merged as a reviewable RFC
  document; this ADR backfills the decision record from what actually shipped.

## Context

Container image references (base images, build-tool images like `common`,
`brew`, `akmods`, `rechunker`, `coreos-chunkah`) were hardcoded to specific
registries and paths throughout the build scripts and workflows. That meant:

- No way to point at a registry mirror (useful for CI reliability, air-gapped
  builds, or regional mirrors) without editing every call site.
- No single place to see every external image dependency the build pulls.
- No consistent digest-pinning story — some references were tag-only, which
  is a supply-chain risk for images that matter (tool images, ISO base
  images).

RFC-009 proposed a design for this. Three `rfc009-registry-mirrors[-v2/-v3]`
branches exist in the repo (per #1093), iterating on the proposal, but **none
of them merged** — the actual implementation shipped directly to `main` in
phases instead, starting with `registry-map.yaml` + `scripts/_registry.sh`
("RFC-009 Phase 1", 2026-06-07) and continuing through Phase 4 (docs + test
suite, 2026-06-09), digest pinning for tool images (2026-06-10), a
routing fix for tacklebox/rechunker (2026-06-13), and consolidation behind
`scripts/resolve-image.sh` as a single entry point (2026-07-06). This is the
"RFC-009 shipped via separate work" case #1093 names explicitly.

## Decision

**Centralize every external image reference in `registry-map.yaml`, resolved
through `scripts/_registry.sh`'s `registry_ref()` function, with environment
variable overrides at three levels (registry host, image path, tag/digest).**

- `registry-map.yaml` maps logical image names (`common`, `brew`, `akmods`,
  `almalinux-bootc`, `coreos-chunkah`, `rechunker`, `bluefin-iso`, ...) to a
  `registry` key (`ghcr`/`quay`/`docker`), a `path`, and either a `tag` or a
  pinned `digest`.
- `registry_ref(name, tag_spec)` resolves a logical name to a fully-qualified
  reference, applying overrides in precedence order: explicit `tag_spec` arg
  → `TUNA_IMAGE_PATH_<name>` → `TUNA_REGISTRY_<key>` → the file's defaults.
  Digest takes precedence over tag when both are present ("security:
  immutable reference", per the script's own comment).
- Security-sensitive tool images (`coreos-chunkah`, `rechunker`, the ISO
  bootc target `bluefin-iso`) are pinned to a digest, not just a tag, so a
  tag mutation upstream can't silently change what a build pulls.
- `scripts/resolve-image.sh` was added later as a single CLI entry point
  consolidating `registry_ref()` with the two other image-metadata sources
  that existed independently (`build-config.yml`'s `base_image` per variant,
  `image-versions.yaml`'s digest pins) — so callers don't need to know which
  of three files actually holds a given image's reference.

### Alternative considered and rejected

The RFC branches' multi-generation churn (v1 → v2 → v3, per #1093) suggests
the design went through real iteration before landing — but since none of
those branches merged and the actual shipped design differs in detail from
what a from-branch archaeology would show, this ADR does not attempt to
reconstruct what specifically changed between v1/v2/v3. That's a gap: if the
rejected intermediate designs matter for future reference, someone with
direct knowledge of those branches should backfill it, rather than this ADR
guessing.

## Consequences

**Positive** — every external image dependency has one source of truth;
mirror/fork overrides are a single environment variable, not a
call-site-by-call-site edit; digest pinning for security-sensitive images is
enforced by the shape of the data (a `digest` field takes precedence
automatically) rather than by convention.

**Negative** — three `rfc009-registry-mirrors-*` branches remain unmerged
and now describe a design that diverged from what shipped; per RFC-PROCESS.md
and #1363, they still need an explicit disposition (most likely: abandon,
since the functionality already shipped through other commits) rather than
being left to imply open, undecided work.

---
*Backfilled per RFC-PROCESS.md / #1094 (ADR coverage gap) — source:
`registry-map.yaml`, `scripts/_registry.sh`, `scripts/resolve-image.sh`, and
their commit history (2026-06-07 through 2026-07-06). Not written by anyone
with direct authorship context on the original RFC-009 branches; corrections
welcome from whoever has that context.*
