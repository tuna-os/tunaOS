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
flagged for triage (stage → Merged, Abandoned, or folded into a successor).

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

## Triage of existing branches (at 2026-08-22 checkpoint)

The 11 existing RFC branches predate this policy. At the Q3 checkpoint
(#1299) each must be assigned one of: **merge** (meets gate today),
**carry** (owner + 30-day plan), or **abandon** (close branch + issue).
No RFC branch may remain un-triaged after 2026-08-31.

## Relationship to ADRs (#1094)

RFCs decide *how*; ADRs record *that the decision was made and why*. A merged
RFC without an ADR is an unrecoverable decision. Every RFC merge therefore
creates or updates a `docs/adr/` entry — this is the mechanism by which the
#1094 coverage gap (2 ADRs for 11+ RFCs) closes over time.

---
*Filed by strategist agent (ACMM L6 — full mode)*
