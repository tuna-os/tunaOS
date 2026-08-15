# Branch Hygiene Policy

**Status**: PROPOSED — 2026-08-14
**Owner**: tuna-os (hanthor) / strategist
**Tracks**: #1530 (Branch hygiene policy), #1174 (Adoption metrics snapshot), #1363 (RFC disposition pass)

---

## Purpose

Define branch naming, lifecycle, staleness rules, and automated/manual cleanup procedures for the `tuna-os/tunaos` repository.

Unmanaged branch accumulation (97+ branches across RFCs, agent runs, and feature experiments) creates contributor friction, obscures active work, and clutters PR targeting. This policy establishes a predictable branch lifecycle so that only active, owned branches remain in the repository.

---

## Branch Naming & Classification

All branches pushed to `tuna-os/tunaos` must follow a recognized prefix convention and carry clear ownership:

| Branch Type | Prefix / Pattern | Max Lifetime | Owner / Responsibility | Disposition |
|---|---|---|---|---|
| **Default Branch** | `main` | Permanent | Maintainers (`tuna-os`) | Protected by GitHub Rulesets ([BRANCH-PROTECTION.md](BRANCH-PROTECTION.md)) |
| **RFC Proposals** | `rfcNNN-<slug>` | 30 days post-commit | Author / Strategist | Governed by [RFC-PROCESS.md](../RFC-PROCESS.md). Merged, abandoned, or deleted after disposition pass. |
| **Feature / Fix** | `feat/<name>`, `fix/<name>`, `docs/<name>`, `ci/<name>`, `arch/<name>` | 30 days post-commit | PR Author | Merged via PR (deleted on merge) or deleted when stale/abandoned. |
| **Agent / Automation** | `agent/<name>`, `claude/<name>`, `codex/<name>`, `auto/<name>` | 14 days post-commit | Agent / Initiator | Transient build or experiment branches. Deleted automatically on PR merge or purged when stale. |
| **Release / Stable** | `release/<version>`, `stable/<version>` | Permanent / Lifecycle | Maintainers | Long-term maintenance refs for stable releases. |

> **Fork-First Policy**: External contributors and agent runs without push access build on their personal forks. Direct upstream branches are reserved for core maintainer workflows, release tags, and tracked RFC proposals.

---

## Staleness Rules & Triage Cadence

A branch is considered **stale** if it has no new commits for **30 days** (14 days for agent/automation branches) and has no open, active Pull Request.

### Triage & Cleanup Rules

1. **Delete-on-Merge (Automated)**:
   GitHub's `delete-branch-on-merge` setting is enabled. Merging a Pull Request automatically deletes the head branch from `tuna-os/tunaos`.

2. **RFC Branch Disposition Pass**:
   RFC branches (`rfcNNN-*`) are triaged in accordance with [RFC-PROCESS.md](../RFC-PROCESS.md) during quarterly checkpoints (e.g. 2026-08-22 Q3 checkpoint #1299 / #1363). Branches whose ideas are merged/absorbed, superseded, or abandoned are deleted from upstream.

3. **Monthly Stale Branch Audit**:
   As part of the monthly [ADOPTION-METRICS.md](../ADOPTION-METRICS.md) and hygiene reporting cycle (#1174), the active branch count across `tuna-os` authorized repositories is audited:
   - Stale unmerged feature/fix/agent branches (>30 days inactive) without an open PR are flagged for deletion.
   - Maintainers or agents run a cleanup pass deleting obsolete tracking branches:
     ```bash
     git push upstream --delete <stale-branch-name>
     ```

---

## Hygiene Metrics & Reporting

Branch count and stale-branch count are tracked in the monthly maintainer hygiene snapshot alongside release and adoption metrics:

- **Target**: Maintain ≤ 15 active upstream branches at any given time (excluding permanent release tags/branches).
- **Metric Linkage**: Reported in the monthly ROADMAP Community & Governance updates (#1174).
