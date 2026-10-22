---
created_date: "2026-10-22"
document_status: final
---

# Public-signal baseline

Spec: [issue-2819-adoption-baseline](../../specs/issue-2819-adoption-baseline.md).

1. Inspect main, the issue and closed PR #2980. Keep this change limited to
   public counters and an artifact workflow; provider setup stays with owners.
2. Add the collector and tests for S1/S2, then execute a dated baseline.
3. Add the monthly workflow and review/publication runbook for S3/S4.
4. Run focused tests, CI contract, format and lint checks; record limitations
   in the PR. Open it against main with signed commits.

Issue dispatch supplies scope acceptance. Procedural confirmation steps are
self-approved under AGENTS.md. `spektacular version check` reports installed
skills 0.20.0 versus CLI 0.22.0; this small plan records the accepted scope
without migrating shared skill files. No RFC or service deployment is needed.
