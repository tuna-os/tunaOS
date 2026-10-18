# RFC 013: One fork-owned config

Status: Draft. Issue: [#3433](https://github.com/tuna-os/tunaOS/issues/3433).
This draft does not approve a rollout or merge.

## Problem and choice

A fork should own one YAML file for its image namespace, supported targets,
packages and brand. Assets may live in referenced files. Today the build matrix,
desktop manifests and brand scripts are separate inputs. `custom/` builds one
base overlay; it does not provide variant fanout.

Keep the existing catalogs and consumers. Add a strict intent layer and move
consumers in small steps. This follows [VISION.md](../../VISION.md). A second
hardcoded catalog would drift; a whole-build rewrite would hide regressions.
Keep `custom/` separate in this phase. Its context-path defect needs its own
execution test and fix, not an unrelated change in this PR.

## Phase 1: Compatibility foundation (this PR)

`scripts/resolve-fork-config.py` reads the closed v1 contract below. It emits a review-only JSON plan with all declared variant/flavor/platform
cells and the original image-build flag. It includes the flavor routes, merged
fork intent, whole legacy catalog and a hash receipt for the sources. Selection marks cells; it
never invents cells or changes a hold. The legacy catalog retains all flags,
rollout records, ISO groups, aliases, stages and base digest pins.

The receipt hashes existing package manifests, build scripts, identity data,
Containerfiles, image pins and committed assets. Only Git-tracked files enter
the receipt; Python bytecode and other temporary output do not. It is a **source snapshot**,
not a resolved package transaction or evidence from a built image. Shell-driven
package lists remain shell-driven. Nothing in this phase installs packages,
configures repositories or changes the image brand.

Use a Git checkout, Python 3.10+ and PyYAML (the existing Python test dependency):

```sh
python3 scripts/resolve-fork-config.py examples/fork/stock.yaml > /tmp/plan.json
python3 scripts/resolve-fork-config.py examples/fork/stock.yaml --format legacy > /tmp/build.json
TUNAOS_BUILD_CONFIG=/tmp/build.json ./scripts/resolve-image.sh yellowfin base
```

The export to the legacy format accepts only stock intent. It fails if image, target, global
or scoped intent is present. It is JSON, which YAML readers accept. It preserves
all catalog values through `TUNAOS_BUILD_CONFIG`; it does not change the default
path. The plan itself is not a build config. Normal builds do not invoke this
command or gain a Python dependency.

### Closed v1 schema

Every mapping rejects unknown keys. YAML duplicate/non-string keys, merge keys,
null values where a mapping is required, wrong types and unknown selectors fail.
No environment expansion, executable hooks or remote includes are supported.

- `schema_version`: required integer `1` (booleans are not integers here).
- `catalog.sha256`: a required hash of the source receipt (64 lowercase hex digits). This pins
  the source bytes in the local checkout, not a mutable branch or remote URL.
  Run `--catalog-pin` to inspect the current hash. Review source changes before
  you update it; the tool never fetches or updates pins. An alternate
  `TUNAOS_BUILD_CONFIG` must have the same bytes as the pinned matrix input.
- `image`: optional mapping with both `registry` and `namespace`, lowercase
  registry/path tokens. Review intent only; no publish-name or URL substitution.
- `targets`: optional `variants`, `flavors`, `platforms`, each a nonempty list of
  known values from the catalog, without duplicates. Omitted axes select all declared values. Selection
  is an intersection over declared cells, not a Cartesian product. No enabled
  match is an error. A selected disabled cell remains disabled. This is not a
  dependency-closed build schedule; parent/base closure belongs to phase 2.
- `global`: optional layer, described below.
- `overrides`: optional `variants`, `desktops`, `cells` mappings of selector to
  layer. Variants use catalog IDs; desktops use manifest-backed desktop IDs;
  cells use exact `variant:flavor` IDs. Unknown selectors fail, including an
  unsupported cell absent from the catalog. No wildcard selectors.

A layer accepts only `branding` and `packages`:

- `branding`: optional `name`, `homepage`, `documentation`, `support`, `logo`,
  `wallpaper` strings. URLs need HTTPS. Assets must exist under the config's
  directory; absolute paths, escapes and outward symlinks fail. Phase 1 checks
  paths, not image formats. Phase 2 must validate format, size and asset receipts.
- `packages`: optional `add`, `remove`, `optional` lists of unique nonempty
  strings and `repositories`, a list of objects with exactly `id`, `url`,
  `key_url`. URLs need HTTPS. No unsigned repository switch. These are native
  package names, not portable cross-family aliases. Scope them to the relevant
  variant. The tool runs no package shell and makes no claim about package availability.

Precedence is upstream source → global → variant → desktop → cell. Upstream
sources stay untouched; the plan records only the delta intent. More specific
brand values replace less specific values.

Lists append in scope order with
stable exact-value deduplication. A package in multiple operation classes is an error, even across scopes.
Move it to the correct scope; do not depend on an implicit remove/re-add. The tool deduplicates repositories from parent scopes. The same ID with different declarations is an error.

Empty lists are
no-ops, not clears. An empty brand value is invalid. No layer deletes a hold.

The future application order is repository setup → explicit removals → required
adds → optional adds. Required package failures must fail the build. The consumer must record
optional misses. Upstream base-package protections and solver conflicts
need validation in phase 2. Phase 1 does not claim to enforce package-manager
semantics from a list of strings.

### Phase 1 evidence and limits

`tests/test_fork_config.py` compares every expanded cell and every flavor route
to the existing inputs. It checks whole-catalog equality, all base-image lookups through the stock
adapter, preserved holds, source hashes and precedence. It also checks strict
validation, pin failure, asset paths and refusal of fork application. Existing
resolver/admission tests remain in place. These source-level tests do not claim image, boot or install acceptance.

## Phase 2: Opt-in consumer adapters

1. Reconcile with the catalog/identity contracts proposed in PR #3431 if that
   work lands. Keep one schema for the catalog. Keep current source ownership
   and the `TUNAOS_BUILD_CONFIG` seam.
2. Generate the internal inputs for the matrix from selected supported cells. Compute parent
   and base closure with the existing resolver. Preserve stages, platform limits,
   disabled cells, the GNOME-only PR filter, release policy and admission gates.
3. Resolve package transactions through each existing family adapter. Record the effective repositories in order, removals, required and optional installs,
   including base scripts and legacy paths. Prove stock parity before the consumer applies
   fork deltas. Test conflicts, missing packages and repeat application.
4. Apply brand values in `90-image-info.sh`, image metadata and desktop settings.
   Cover both `install-desktop.sh` and Debian/Ubuntu's
   `configure-desktop-runtime.sh`; [the brand guide](../../BRANDING.md) records why
   a change to one path is insufficient. Handle fish names, URLs, CPE, logo and
   installer identity explicitly.
5. Generate fork assets before the build, commit or hash those assets,
   and pass them to both paths. Current the repo contains generated assets; builds
   do not regenerate them. Check wallpaper, logo, greeter and Plymouth in the
   produced image. Missing greeter/Plymouth evidence is a verification gap,
   not a reproduced runtime failure.
6. Run one fork canary per package family and desktop. Compare a stock canary
   to the legacy path. Keep each adapter independently revertible.

## Phase 3: Supported fanout and retirement

Fan out the fork file over declared supported cells only. For every release
cell, need build, boot, login, install and visible-brand evidence tied to
its source config and immutable image. Keep unsupported reasons and hardware
holds until their own admission evidence changes. Do not equate a green plan
with a desktop or installer that works.

Only retire legacy overrides after those consumers and acceptance checks pass.
For rollback, use the unchanged legacy path and revert the adapters. Keep
pinned catalog/base inputs and provenance with each plan. Maintainers must sign off and write an ADR under [RFC-PROCESS.md](../../RFC-PROCESS.md).
