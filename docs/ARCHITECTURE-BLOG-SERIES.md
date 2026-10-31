# Architecture and adoption blog series

Issue [#3301](https://github.com/tuna-os/tunaos/issues/3301) requests a series
for first-time users, infrastructure teams, and distribution maintainers.
The blog source belongs in [tuna-os/docs](https://github.com/tuna-os/docs),
not in this repository's developer references.

## Drafts for editorial review

[Docs PR #636](https://github.com/tuna-os/docs/pull/636) contains three linked
posts and a claim-evidence ledger. The following links pin the submitted copy
at commit `a34331704bd2d143a7648eee483d7cbebe8215eb`:

| Draft | Scope |
| --- | --- |
| [Getting Started with TunaOS: Choosing Your Variant](https://github.com/thatguywob/docs/blob/a34331704bd2d143a7648eee483d7cbebe8215eb/blog/2026-10-24-choosing-your-tunaos-variant.md) | Base-family comparison, desktop choices, artifact verification, installation and compatible-host switch example |
| [Cloud-Native Linux Desktop: Architecture and Bootc Integration](https://github.com/thatguywob/docs/blob/a34331704bd2d143a7648eee483d7cbebe8215eb/blog/2026-10-24-cloud-native-desktop-architecture.md) | Build graph, deployment and mutable-state boundaries, rollback limits, overlays and reproducibility claims |
| [Multi-Variant Strategy: Lessons from TunaOS](https://github.com/thatguywob/docs/blob/a34331704bd2d143a7648eee483d7cbebe8215eb/blog/2026-10-24-multi-variant-strategy.md) | Configuration ownership, package-family differences, per-cell tests, lifecycle and contribution workflow |

The [editorial review guide](https://github.com/thatguywob/docs/blob/a34331704bd2d143a7648eee483d7cbebe8215eb/runbooks/architecture-series-review.md)
contains outlines, pinned evidence, validation results, and publication steps.
The architecture draft includes the bootc trade-offs proposed for the optional
fourth article. A historical case study still needs named human sources and
verified outcomes; the drafts do not invent founder statements or adopter results.

## Technical constraints for reviewers

Run the [content claim checklist](CONTENT-CLAIM-CHECKLIST.md) before expanding
or publishing the copy. The source audit at `a6fcff42` establishes these boundaries:

- [tunaos.toml](../tunaos.toml) owns the variant matrix and desktop package data.
  The issue's `build-config.yml` pointer predates primary TOML ownership.
  Scripts can still consume generated adapters; edit the policy source rather
  than a generated manifest. See the [migration reference](PRIMARY-CONFIG-MIGRATION.md).
- The [variant workflow](../.github/workflows/build-variant.yml) uses Containerfile
  builds. BuildStream-based sibling products appear separately in the primary
  configuration. Their engine and test results do not apply to every variant.
- [Input pins](../image-versions.yaml), a source commit, and a signed output digest
  provide traceability. They do not prove a byte-identical rebuild. No rebuild
  comparison was performed for this series.
- Upstream [bootc filesystem semantics](https://bootc.dev/bootc/filesystem.html)
  distinguish OS content from mutable state. [Rollback](https://bootc.dev/bootc/man/bootc-rollback.8.html)
  selects a retained deployment; it is not a whole-machine or database restore.
- A declared cell is not evidence of a successful install. Keep operational
  status in the [generated matrix](MATRIX-STATUS.md) under the
  [green criteria](GREEN-CRITERIA.md), rather than copying it into blog prose.

## Remaining editorial work

The issue requests a hold-labeled PR for human review. The docs PR is ready
for review, and each post retains `draft: true` so the production build excludes
it. Adding the `hold` label was denied by GitHub permissions; a maintainer must
apply it before admitting the PR to merge.

The copy is shorter than the proposed final word targets. Review scope, add
measured pilot examples where useful, refresh the evidence and dates, and
approve publication before removing draft flags. No installation, hardware
pilot, or reproducibility test is claimed by the prose.

Docs preflight, changed-file Markdown lint, and hidden and visible-draft builds
passed for the submitted copy. The browser audit could not launch Chromium
because the contributor host lacks `libglib-2.0.so.0`. Rerun the docs repository's
`just preflight`, `just build`, and `npm run a11y` after editorial changes and
before publication. Keep #3301 open through that review and publication work.
