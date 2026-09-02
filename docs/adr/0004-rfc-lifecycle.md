# ADR 0004: RFC lifecycle policy (RFC-PROCESS.md)

- Status: accepted (policy merged)
- Date: 2026-08-11
- Last updated: 2026-08-12
- Issue: [#1093](https://github.com/tuna-os/tunaOS/issues/1093)
- Policy: [RFC-PROCESS.md](../../RFC-PROCESS.md) (merged via [#1352](https://github.com/tuna-os/tunaOS/pull/1352))

## Context

Architectural and process proposals ("RFCs") in tunaOS had no lifecycle.
As of 2026-08-11, **11 RFC branches** (`rfc001`–`rfc009`, several with `-v2`/
`-v3` successors) sat in the repo, all last touched **2 months earlier**
(2026-06-06/06-08), with **no reviewable RFC document on any of them** and no
`docs/rfc/` directory at all. Decisions that *had* been made were unrecorded:
only 2 ADRs existed for 11+ RFC-sized changes (#1094), so the repo's decision
history was unrecoverable for anyone not present when the branch was pushed.

The Q3 2026 checkpoint (#1299, 2026-08-22) required an RFC merge-policy
document merged by 2026-09-01 as the STAFF test for #1093 — i.e. governance
had to exist *before* the existing branch backlog could be disposed of.

## Decision

**Adopt the RFC lifecycle policy defined in RFC-PROCESS.md.**

- Five stages: **Draft → Review → Merged → ADR**, with **Abandoned** as the
  explicit close path.
- A branch named `rfcNNN-*` may merge only when it satisfies the **merge
  gate**: (1) an RFC document at `docs/rfc/rfcNNN-title.md`, (2) an open
  tracking issue linking the RFC number, branch, and owner, (3) maintainer
  sign-off on the approach, and (4) an ADR recorded on merge — so ADR
  coverage (#1094) keeps pace with decisions.
- Branches that cannot meet the gate within **30 days** of the last commit
  are flagged for triage (merged, abandoned, or folded into a successor).
- Small, contained changes (script fixes, single manifest edits) do **not**
  require an RFC — the gate applies to cross-cutting architectural or process
  proposals only.

Explicitly rejected alternatives:

- **Ad-hoc RFCs without a gate**: preserves the status quo where branches
  accumulate with no document, no owner, and no exit — the exact failure the
  policy exists to fix.
- **RFCs as PRs only, no branch convention**: loses the numbered-branch audit
  trail and makes the 30-day triage trigger unenforceable.

## Consequences

**Positive** — the backlog becomes tractable: the policy gives every one of
the 11 extant branches an explicit disposition path and a deadline; decisions
now produce ADRs automatically, closing the #1094 coverage gap structurally
rather than by campaign.

**Negative** — the policy is only as good as its application: the 11 existing
branches still need a one-pass disposition audit (new issue #1363), and the
30-day triage rule requires someone to actually run the sweep — otherwise the
policy becomes governance theater.

---
*Recorded by strategist agent per RFC lifecycle policy (RFC-PROCESS.md, #1093/#1094).*
