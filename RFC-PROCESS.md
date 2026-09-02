# tunaOS RFC Lifecycle Policy

**Status**: ACCEPTED — merged 2026-08-11 via [#1352](https://github.com/tuna-os/tunaOS/pull/1352), recorded in [ADR 0004](docs/adr/0004-rfc-lifecycle.md)
**Owner**: tuna-os (hanthor) / strategist
**Tracks**: #1093 (RFC lifecycle governance), #1094 (ADR coverage), #1363 (11-branch disposition pass)

## Purpose

Define how architectural and process proposals ("RFCs") enter, review, merge,
and become decision records in tunaOS. Without a lifecycle, RFC work is
trapped in long-lived branches that never merge and never become auditable
decisions.

**Current state (2026-08-11)**: 11 RFC branches sit in the repo, all
last-touched 2026-06-06/06-08 — **2 months stale**. None carry a reviewable
RFC document; the ROADMAP cites "RFC 010" (Grouper) with no `rfc010` branch
and no RFC docs directory exists. The Q3 2026 checkpoint (2026-08-22, #1299)
requires an **RFC merge policy doc merged by 2026-09-01** as the STAFF test
for #1093.

## Scope

Applies to any branch named `rfcNNN-*` and any proposal that introduces a
cross-cutting architectural or process change (build system, CI gates, image
layout, package sourcing, variant mechanics). Small, contained changes (a
script fix, a single manifest edit) go through normal PR review and do **not**
need an RFC.

## Lifecycle stages

| Stage | Meaning | Entry criteria | Exit criteria |
|-------|---------|----------------|---------------|
| **Draft** | Proposal under discussion | RFC doc + tracking issue filed | Reviewed → Decision |
| **Review** | Open for comment | At least one maintainer + one agent review | Decision reached |
| **Merged** | Code/design lands on `main` | Merge gate below satisfied | ADR recorded |
| **ADR** | Decision recorded for the future | Merged RFC + docs/adr entry | — |
| **Abandoned** | Proposal withdrawn | Explicit close with reason | Closed issue |

## Merge gate — what an RFC needs to land

An RFC branch may merge only when **all** of the following hold:

1. **RFC document present** — the branch carries `docs/rfc/rfcNNN-title.md`
   describing the problem, options considered, and the chosen approach.
2. **Tracking issue open** — an issue links the RFC number, lists the branch,
   and names an owner (mirrors the variant admission gate #1196/#1270).
3. **Maintainer sign-off** — a maintainer comment approving the approach, not
   just the diff.
4. **ADRs on merge** — merging an RFC is followed by (or accompanied by) a
   `docs/adr/` entry recording the decision, so #1094 coverage keeps pace.
   The decision record may be brief (context + decision + consequences).

Branches that cannot meet the gate within **30 days** of the last commit are
flagged for triage (stage → Merged, Abandoned, or folded into a successor) per [BRANCH-HYGIENE.md](docs/BRANCH-HYGIENE.md).

## Numbering and branch conventions

- RFC numbers are **allocated sequentially by the tracking issue**, never
  reused. The current registry (derived from branches + ROADMAP references):
  `001` hw-variant-param, `003` consolidate-agent-files, `004` ci-gate
  generated-workflows, `005` directory-readmes, `006` justfile-modular-split,
  `007` upstream-sync-script, `008` gdx→nvidia, `009` registry-mirrors,
  `010` Grouper (referenced in ROADMAP).
- `002` was never allocated; numbers `010+` are reserved for new proposals.
- Branch shape: `rfcNNN-<slug>`; iterative versions use `-v2`, `-v3`
  **only** on the same proposal number, never a new number.

## Triage of existing branches (disposition pass, #1363, 2026-08-13)

The 11 existing RFC branches predate this policy and none carries a
`docs/rfc/rfcNNN-*.md` document, so none can meet the merge gate above as
written — the gate is a forward-looking bar for *new* proposals, not a test
these branches were ever measured against. Disposition here is instead based
on whether each branch's actual code content already shipped to `main`
through a different path (2 months of drift — 3,652+ commits — makes this
common), is still a live, un-shipped proposal, or is a zero-diff historical
ref.

| Branch | Unique commits | Disposition | Evidence |
|---|---|---|---|
| `rfc001-phase1-hw-variant-param` | 5 | **Abandon** | Proposed a single parametrized Containerfile (`HW_VARIANT` build arg). Main took a different direction instead: per-base `Containerfile.{el10,ubuntu,debian,arch,gentoo,opensuse}` files. No `HW_VARIANT` anywhere in the tree. Superseded by an architectural choice, not absorbed. |
| `rfc001-phase1-hw-variant-param-v2` | 0 | **Delete** | Zero commits ahead of `main` — every commit on this branch is already an ancestor of `main`. Pure dead ref. |
| `rfc003-consolidate-agent-files` | 1 | **Abandon (absorbed)** | Proposed consolidating triplicate agent files into `AGENTS.md`. `AGENTS.md` already exists at repo root, landed via a different commit. Outcome shipped; this branch's specific diff didn't. |
| `rfc004-ci-gate-generated-workflows` | 1 | **Abandon** | Proposed a Python generator (`scripts/generate-workflows.py`) producing exactly the then-4 per-variant workflow files, with a CI drift gate. The repo now has 17 `build-*.yml` files with a materially different structure — the branch's specific generator design no longer fits current architecture. The underlying idea (drift protection for generated files) is still sound and could be re-proposed fresh against today's workflow set. |
| `rfc005-directory-readmes` | 1 | **Merged (this PR)** | Proposed `scripts/README.md` + `build_scripts/README.md` clarifying the boundary. `build_scripts/README.md` already existed on `main`; `scripts/README.md` was still missing. Added it in this PR (fresh content — the branch's original copy referenced the pre-RFC-006 monolithic `Justfile`, since replaced by `just/`). |
| `rfc006-justfile-modular-split` | 7 | **Abandon (absorbed)** | Proposed splitting a 787-line monolithic `Justfile` into modules. `just/` already exists with the modular structure (`just/utilities.just`, `just/custom-overlay.just`, etc.), landed via different commits. |
| `rfc007-upstream-sync-script` | 1 | **Abandon (absorbed)** | Proposed `scripts/sync-upstream-snapshots.sh`. Already exists on `main` under the same name. |
| `rfc008-gdx-to-nvidia` | 8 | **Abandon (absorbed)** | Rename already shipped and recorded in [ADR 0001](docs/adr/0001-gdx-to-nvidia-rename.md) — confirmed dead weight, as this issue itself named. |
| `rfc009-registry-mirrors` | 1 | **Abandon (absorbed)** | `registry-map.yaml` already exists on `main`. [ADR 0007](docs/adr/0007-registry-mirror-support.md) explicitly documents it "shipped directly to main, not via the rfc009-registry-mirrors-* branches." |
| `rfc009-registry-mirrors-v2` | 1 | **Abandon (absorbed)** | Same as above — see ADR 0007. |
| `rfc009-registry-mirrors-v3` | 1 | **Abandon (absorbed)** | Same as above — see ADR 0007. |

**Net**: 1 merged (rfc005, this PR), 1 deleted as a zero-diff ref
(rfc001-v2), 9 abandoned (8 already absorbed into `main` through other
commits, 1 superseded by a different architectural direction). None require
carrying forward — every unresolved idea worth keeping (rfc004's drift-gate
concept) is called out above for a fresh RFC against current architecture,
not a revival of stale branch content.

Branch deletion itself requires push access this contributor doesn't have;
the maintainer command to execute this disposition is:

```bash
git push upstream --delete \
  rfc001-phase1-hw-variant-param rfc001-phase1-hw-variant-param-v2 \
  rfc003-consolidate-agent-files rfc004-ci-gate-generated-workflows \
  rfc005-directory-readmes rfc006-justfile-modular-split \
  rfc007-upstream-sync-script rfc008-gdx-to-nvidia \
  rfc009-registry-mirrors rfc009-registry-mirrors-v2 rfc009-registry-mirrors-v3
```

(`rfc005` is safe to delete too once this PR merges — its content is now on
`main` directly, not via the branch.)

## Relationship to ADRs (#1094)

RFCs decide *how*; ADRs record *that the decision was made and why*. A merged
RFC without an ADR is an unrecoverable decision. Every RFC merge therefore
creates or updates a `docs/adr/` entry — this is the mechanism by which the
#1094 coverage gap (2 ADRs for 11+ RFCs) closes over time.

---
*Filed by strategist agent (ACMM L6 — full mode)*
