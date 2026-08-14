# Branch Hygiene & Lifecycle Policy

**Status**: Published Policy  
**Tracks**: [#1530](https://github.com/tuna-os/tunaOS/issues/1530) (Branch hygiene policy missing)  
**Applies to**: `tuna-os/tunaos` and all active repositories in the `tuna-os` organization.

---

## 🎯 Purpose

As the `tuna-os` organization grows across multi-agent workflows and community contributions, maintaining a clean branch namespace is vital to:
- Reduce onboarding friction for external contributors finding active base branches.
- Prevent stale, orphaned feature or experiment branches from accumulating.
- Ensure clear disposition timelines for Architecture RFC proposals.
- Keep repository metrics and status tracking clean.

---

## 📐 Branch Naming Conventions

All branches created in `tuna-os` repositories must follow standard prefixes matching their intent:

| Prefix | Purpose | Owner & Lifecycle |
|---|---|---|
| `main` | Production / default branch | Protected by rulesets; persistent |
| `feat/*` / `fix/*` | Feature development & bug fixes | Contributor/Agent; deleted upon merge |
| `ci/*` / `arch/*` | CI workflows & architectural updates | Core/Agent; deleted upon merge |
| `strategy/*` / `outreach/*` | Roadmap, planning, and community docs | Core/Agent; deleted upon merge |
| `rfc/rfcXXX-*` | Architecture RFC proposals | Proposer; evaluated at checkpoint (#1363) |
| `renovate/*` / `dependabot/*` | Automated dependency updates | Bot; auto-pruned upon merge/supersede |

---

## 🔄 Branch Lifecycle Rules

### 1. Feature & Fix Branches (`feat/*`, `fix/*`, `ci/*`, `arch/*`, `strategy/*`)
- **Delete on Merge**: Repository settings enforce `delete_branch_on_merge: true`. All merged PR branches are automatically deleted from the remote.
- **Stale Branch Limit (30 Days)**: Unmerged feature or fix branches with no commit activity for >30 days will be flagged during monthly triage and deleted or archived if abandoned.

### 2. RFC Branches (`rfc/rfcXXX-*`)
- **Checkpoint Disposition**: RFC branches created for Architecture RFC proposals (e.g., `rfc001` through `rfc009`) are formally dispositioned at scheduled community checkpoints (e.g., Q3 2026 checkpoint #1363).
- **Outcome Handling**:
  - **Accepted**: Merged into `main` (e.g. into `docs/adr/` or `docs/`) and remote branch deleted.
  - **Rejected / Superseded**: Closed and deleted from remote; historical record maintained in issue tracker / ADR index.

### 3. Experimental & Spike Branches (`exp/*`, `diag/*`)
- **Temporary Scope**: Diagnostic and spike branches must have a designated owner (human or agent lane).
- **14-Day Limit**: Spike branches must be resolved, converted to a PR, or deleted within 14 days.

---

## 🧹 Org-Wide Triage & Metrics Integration

1. **Monthly Branch Triage**:
   - Pre-release / pre-checkpoint sweeps audit the total remote branch count.
   - Any branch exceeding staleness limits without an active tracking issue is pruned.
2. **Adoption Metrics Tracking**:
   - Total active branch count across the organization is tracked as a hygiene metric in monthly `ADOPTION-METRICS.md` snapshots (#1174).
