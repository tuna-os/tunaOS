# Plan: protected native-package removal

## Phase 0: approve the design

- Review
  [the F4b specification](../../specs/20261024100000-protected-native-package-removal.md)
  against issue #3803 and the primary-config package work in #3739.
- Record maintainer approval of the exact revision before implementation.
- Keep every production validator and consumer rejection for removal intent.

**Exit:** explicit maintainer approval exists. A merge without that approval does
not authorize implementation or enablement.

## Phase 1: compile protection from existing contracts

- Extend the primary parser/resolver branch after the F4 additions stack lands;
  do not create a fork-only schema or generated catalog.
- Resolve native identities and file/unit owners from the effective package,
  base, desktop and runtime contracts in the disposable build root.
- Emit a content-addressed protected-set receipt with source, config, images,
  repositories, inventory, tools and reason provenance.
- Fail closed when a contract cannot be projected completely.

**Exit:** source tests prove exact inheritance/conflict semantics, complete
provenance, contract drift invalidation and no package-manager invocation on all
rejections. Removal remains disabled.

## Phase 2: add native transaction qualification

- Implement one adapter at a time for dnf/libdnf, apt/dpkg, pacman and
  zypper/libzypp. Keep Portage and unknown managers rejected.
- Capture the complete native solver closure, reject protected or unrelated
  actions, and execute the candidate in a disposable private root.
- Compare complete before/after inventories and contract results. Discard every
  qualification root. Adopt relevant isolated fixtures from #3444/#3449 rather
  than duplicating their helper or inventory concepts.
- Exercise all adversarial fixtures in specification clause `PR-7`.

**Exit:** native transaction artifacts exist for exact pinned environments, with
zero required skips and no production caller.

## Phase 3: wire a disabled image-build path

- Re-resolve the transaction immediately before mutation and require the
  approved fingerprint.
- Apply removal before required and optional additions only in a disposable
  image build. Write the success receipt after final inventory and contract
  checks.
- Gate later image stages and publication on that receipt when removal intent is
  present. The admission map starts empty.

**Exit:** configured removal is still rejected for every unqualified cell; a
maintainer can review the full disabled path and its receipts without a release
or runtime change.

## Phase 4: qualify and admit cells independently

For each exact cell, record source tests, native transaction, built image, boot,
login, separate-target installation, media-detached reboot, update and recovery
results. Missing or moved inputs invalidate admission. Add an admission record
only after maintainer review of that cell's immutable evidence.

**Exit:** only explicitly admitted cells accept removal intent. Every other
cell, Portage and unknown families fail before mutation.

## Delivery boundaries

- #3474 owns built-image/install/update/recovery journey evidence; reuse exact
  matching receipts rather than rerunning or reclassifying unrelated evidence.
- #3668/#3739 own primary configuration and package-addition integration.
- #3444/#3449 remain qualification research until deliberately adopted onto the
  primary implementation after approval.
- No phase authorizes merge, publication, deployment, credential changes,
  safety-hold removal or widening the supported matrix.
